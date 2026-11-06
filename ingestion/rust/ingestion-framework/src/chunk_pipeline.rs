use std::sync::{Arc, Mutex};
use std::time::Instant;

use async_trait::async_trait;

use crate::context::{ChunkResults, OkResultWithContext, ResultWithContext};
use crate::metrics::{record_budget_checkpoint, record_step_duration, BudgetCheckpoint};
use crate::pipeline::DynPipeline;
use crate::results::{NonOk, Outcome};
use crate::steps::ChunkProcessingStep;

/// `&self`, because a stage takes a `feed()` while a `next()` is parked, as in Node. Never overlap two `next()` calls.
#[async_trait]
pub trait ChunkPipeline<I, O, CI, CO>: Send + Sync {
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>);
    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>>;
}

pub type DynChunkPipeline<I, O, CI, CO> = Arc<dyn ChunkPipeline<I, O, CI, CO>>;

pub struct BufferingChunkPipeline<T, C> {
    buffer: Mutex<Vec<ResultWithContext<T, C>>>,
}

impl<T, C> Default for BufferingChunkPipeline<T, C> {
    fn default() -> Self {
        Self {
            buffer: Mutex::new(Vec::new()),
        }
    }
}

impl<T, C> BufferingChunkPipeline<T, C> {
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl<T: Send + 'static, C: Send + 'static> ChunkPipeline<T, T, C, C>
    for BufferingChunkPipeline<T, C>
{
    fn feed(&self, elements: Vec<OkResultWithContext<T, C>>) {
        self.buffer
            .lock()
            .unwrap()
            .extend(elements.into_iter().map(OkResultWithContext::into_result));
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<T, C>>> {
        let results = std::mem::take(&mut *self.buffer.lock().unwrap());
        Ok(if results.is_empty() {
            None
        } else {
            Some(results)
        })
    }
}

/// The budget check runs per element, because one chunk can hold elements of batches with different budgets.
pub async fn apply_chunk_step_to_results<T, U, C>(
    step: &ChunkProcessingStep<T, U>,
    items: ChunkResults<T, C>,
) -> anyhow::Result<ChunkResults<U, C>>
where
    T: Send + 'static,
    U: Send + 'static,
{
    let step_name = step.name();
    enum Slot<U, C> {
        Done(ResultWithContext<U, C>),
        CutOff(crate::context::PipelineContext<C>),
        Pending(crate::context::PipelineContext<C>),
    }

    let mut slots: Vec<Slot<U, C>> = Vec::with_capacity(items.len());
    let mut values: Vec<T> = Vec::with_capacity(items.len());
    for item in items {
        match item.result {
            Outcome::NonOk(non_ok) => slots.push(Slot::Done(ResultWithContext {
                result: Outcome::NonOk(non_ok),
                context: item.context,
            })),
            Outcome::Ok(value) => {
                if item.context.budget.as_ref().is_some_and(|b| b.exhausted()) {
                    record_budget_checkpoint(BudgetCheckpoint::Chunk, step_name.clone());
                    slots.push(Slot::CutOff(item.context));
                } else {
                    values.push(value);
                    slots.push(Slot::Pending(item.context));
                }
            }
        }
    }

    let mut step_results = Vec::new();
    if !values.is_empty() {
        let value_count = values.len();
        let started = Instant::now();
        match step.call(values).await {
            Ok(results) => {
                record_step_duration(
                    step_name.clone(),
                    "chunk",
                    "chunk",
                    started.elapsed().as_secs_f64(),
                );
                step_results = results;
            }
            Err(error) => {
                record_step_duration(
                    step_name.clone(),
                    "chunk",
                    "exception",
                    started.elapsed().as_secs_f64(),
                );
                // Node logs the origin of every OK item, also of the items the budget cut off.
                let debug_contexts: Vec<_> = slots
                    .iter()
                    .filter_map(|s| match s {
                        Slot::Pending(c) | Slot::CutOff(c) => c.debug_context.clone(),
                        Slot::Done(_) => None,
                    })
                    .collect();
                tracing::error!(
                    step = %step_name,
                    error = %error,
                    chunk_size = value_count,
                    debug_context = ?debug_contexts,
                    "Chunk step threw"
                );
                return Err(error);
            }
        }
        if step_results.len() != value_count {
            anyhow::bail!(
                "Chunk pipeline step {} returned different number of results than input values: {} !== {}",
                step_name,
                step_results.len(),
                value_count
            );
        }
    }

    let mut step_results = step_results.into_iter();
    Ok(slots
        .into_iter()
        .map(|slot| match slot {
            Slot::Done(done) => done,
            Slot::CutOff(context) => ResultWithContext {
                result: Outcome::NonOk(NonOk::Timeout {
                    reason: format!("budget exceeded before {step_name}"),
                }),
                context,
            },
            Slot::Pending(mut context) => {
                let result = step_results.next().expect("length checked above");
                let outcome = context.absorb_step(step_name, result);
                ResultWithContext {
                    result: outcome,
                    context,
                }
            }
        })
        .collect())
}

pub struct BaseChunkPipeline<I, M, O, CI, CO> {
    step: ChunkProcessingStep<M, O>,
    previous: DynChunkPipeline<I, M, CI, CO>,
}

impl<I, M, O, CI, CO> BaseChunkPipeline<I, M, O, CI, CO> {
    pub fn new(step: ChunkProcessingStep<M, O>, previous: DynChunkPipeline<I, M, CI, CO>) -> Self {
        Self { step, previous }
    }
}

#[async_trait]
impl<I, M, O, CI, CO> ChunkPipeline<I, O, CI, CO> for BaseChunkPipeline<I, M, O, CI, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.previous.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        match self.previous.next().await? {
            None => Ok(None),
            Some(results) => Ok(Some(
                apply_chunk_step_to_results(&self.step, results).await?,
            )),
        }
    }
}

pub struct SequentialChunkPipeline<I, M, O, CI, CO> {
    processor: DynPipeline<M, O, CO>,
    previous: DynChunkPipeline<I, M, CI, CO>,
}

impl<I, M, O, CI, CO> SequentialChunkPipeline<I, M, O, CI, CO> {
    pub fn new(processor: DynPipeline<M, O, CO>, previous: DynChunkPipeline<I, M, CI, CO>) -> Self {
        Self {
            processor,
            previous,
        }
    }
}

pub(crate) async fn process_sequentially<M, O, C>(
    processor: &DynPipeline<M, O, C>,
    items: ChunkResults<M, C>,
) -> anyhow::Result<ChunkResults<O, C>>
where
    M: Send + 'static,
    O: Send + 'static,
    C: Send + 'static,
{
    let mut results = Vec::with_capacity(items.len());
    for item in items {
        match item.into_ok() {
            Ok(ok) => results.push(processor.process(ok).await?),
            Err((non_ok, context)) => {
                results.push(ResultWithContext::<M, C>::non_ok(non_ok, context))
            }
        }
    }
    Ok(results)
}

#[async_trait]
impl<I, M, O, CI, CO> ChunkPipeline<I, O, CI, CO> for SequentialChunkPipeline<I, M, O, CI, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.previous.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        match self.previous.next().await? {
            None => Ok(None),
            Some(results) => Ok(Some(process_sequentially(&self.processor, results).await?)),
        }
    }
}

pub struct GatheringChunkPipeline<I, O, CI, CO> {
    sub: DynChunkPipeline<I, O, CI, CO>,
}

impl<I, O, CI, CO> GatheringChunkPipeline<I, O, CI, CO> {
    pub fn new(sub: DynChunkPipeline<I, O, CI, CO>) -> Self {
        Self { sub }
    }
}

#[async_trait]
impl<I, O, CI, CO> ChunkPipeline<I, O, CI, CO> for GatheringChunkPipeline<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.sub.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        let mut all = Vec::new();
        while let Some(chunk) = self.sub.next().await? {
            all.extend(chunk);
        }
        Ok(if all.is_empty() { None } else { Some(all) })
    }
}

pub struct ChunkPipelineUnwrapper<I, O, C> {
    pipeline: DynChunkPipeline<I, O, C, C>,
}

impl<I: Send + 'static, O: Send + 'static, C: Send + 'static> ChunkPipelineUnwrapper<I, O, C> {
    pub fn new(pipeline: DynChunkPipeline<I, O, C, C>) -> Self {
        Self { pipeline }
    }

    pub fn feed(&self, elements: Vec<OkResultWithContext<I, C>>) {
        self.pipeline.feed(elements)
    }

    pub async fn next(&self) -> anyhow::Result<Option<Vec<O>>> {
        let Some(results) = self.pipeline.next().await? else {
            return Ok(None);
        };
        let mut values = Vec::with_capacity(results.len());
        let mut side_effects = 0;
        for result in results {
            side_effects += result.context.side_effects.len();
            if let Outcome::Ok(value) = result.result {
                values.push(value);
            }
        }
        if side_effects > 0 {
            tracing::warn!(
                "ChunkPipelineUnwrapper found {side_effects} remaining side effects that were not handled"
            );
        }
        Ok(Some(values))
    }
}
