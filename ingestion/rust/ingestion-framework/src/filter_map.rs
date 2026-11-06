//! Rust has no union types, so the output context implements `From` the earlier one for passthroughs.

use std::sync::Arc;

use async_trait::async_trait;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, ResultWithContext};
use crate::interleaving::{InterleavingCallbacks, InterleavingChunkPipeline, PullOutcome};

pub type FilterMapMappingFunction<T, U, C, CM> =
    Arc<dyn Fn(OkResultWithContext<T, C>) -> OkResultWithContext<U, CM> + Send + Sync>;

struct FilterMapCallbacks<I, M, MM, O, CI, CM, CMM, CO> {
    previous: DynChunkPipeline<I, M, CI, CM>,
    mapping: FilterMapMappingFunction<M, MM, CM, CMM>,
    sub: DynChunkPipeline<MM, O, CMM, CO>,
}

#[async_trait]
impl<I, M, MM, O, CI, CM, CMM, CO> InterleavingCallbacks<I, O, CI, CO>
    for FilterMapCallbacks<I, M, MM, O, CI, CM, CMM, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    MM: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CM: Send + 'static,
    CMM: Send + 'static,
    CO: From<CM> + Send + 'static,
{
    fn on_feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.previous.feed(elements);
    }

    async fn on_source_pull(&self) -> anyhow::Result<PullOutcome<O, CO>> {
        let Some(previous) = self.previous.next().await? else {
            return Ok(PullOutcome::Drained);
        };
        let mut ok = Vec::new();
        let mut non_ok = Vec::new();
        for element in previous {
            match element.into_ok() {
                Ok(element) => ok.push((self.mapping)(element)),
                Err((n, context)) => non_ok.push(ResultWithContext::<M, CO>::non_ok(
                    n,
                    context.map_data(CO::from),
                )),
            }
        }
        let had_ok = !ok.is_empty();
        if had_ok {
            self.sub.feed(ok);
        }
        if !non_ok.is_empty() {
            return Ok(PullOutcome::Emit(non_ok));
        }
        // A non-empty upstream chunk with nothing in it surfaces as an empty chunk, 1:1.
        if !had_ok {
            return Ok(PullOutcome::Emit(Vec::new()));
        }
        Ok(PullOutcome::Drain)
    }

    async fn on_process_pull(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        self.sub.next().await
    }
}

pub struct FilterMapChunkPipeline<I, M, MM, O, CI, CM, CMM, CO> {
    inner: Inner<I, M, MM, O, CI, CM, CMM, CO>,
}

type Inner<I, M, MM, O, CI, CM, CMM, CO> =
    InterleavingChunkPipeline<I, O, CI, CO, FilterMapCallbacks<I, M, MM, O, CI, CM, CMM, CO>>;

impl<I, M, MM, O, CI, CM, CMM, CO> FilterMapChunkPipeline<I, M, MM, O, CI, CM, CMM, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    MM: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CM: Send + 'static,
    CMM: Send + 'static,
    CO: From<CM> + Send + 'static,
{
    pub fn new(
        previous: DynChunkPipeline<I, M, CI, CM>,
        mapping: FilterMapMappingFunction<M, MM, CM, CMM>,
        sub: DynChunkPipeline<MM, O, CMM, CO>,
    ) -> Self {
        Self {
            inner: InterleavingChunkPipeline::new(Arc::new(FilterMapCallbacks {
                previous,
                mapping,
                sub,
            })),
        }
    }
}

#[async_trait]
impl<I, M, MM, O, CI, CM, CMM, CO> ChunkPipeline<I, O, CI, CO>
    for FilterMapChunkPipeline<I, M, MM, O, CI, CM, CMM, CO>
where
    I: Send + 'static,
    M: Send + 'static,
    MM: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CM: Send + 'static,
    CMM: Send + 'static,
    CO: From<CM> + Send + 'static,
{
    fn feed(&self, elements: Vec<OkResultWithContext<I, CI>>) {
        self.inner.feed(elements)
    }

    async fn next(&self) -> anyhow::Result<Option<ChunkResults<O, CO>>> {
        self.inner.next().await
    }
}
