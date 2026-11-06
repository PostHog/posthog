use std::sync::Arc;

use async_trait::async_trait;

use crate::chunk_pipeline::{ChunkPipeline, DynChunkPipeline};
use crate::context::{ChunkResults, OkResultWithContext, ResultWithContext};
use crate::metrics::record_side_effect_result;
use crate::pipeline::{DynPipeline, Pipeline};
use crate::side_effects::{SideEffect, SideEffectScheduler};

#[derive(Debug, Clone, Copy, Default)]
pub struct SideEffectHandlingConfig {
    pub await_side_effects: bool,
}

async fn handle(
    scheduler: &dyn SideEffectScheduler,
    config: SideEffectHandlingConfig,
    side_effects: Vec<SideEffect>,
) {
    if side_effects.is_empty() {
        return;
    }
    if config.await_side_effects {
        let settled =
            futures::future::join_all(side_effects.into_iter().map(SideEffect::wait)).await;
        for result in settled {
            record_side_effect_result(result.is_ok());
        }
    } else {
        for side_effect in side_effects {
            scheduler.schedule(side_effect);
        }
    }
}

pub struct SideEffectHandlingPipeline<I, O, CI, CO> {
    sub: DynChunkPipeline<I, O, CI, CO>,
    scheduler: Arc<dyn SideEffectScheduler>,
    config: SideEffectHandlingConfig,
}

impl<I, O, CI, CO> SideEffectHandlingPipeline<I, O, CI, CO> {
    pub fn new(
        sub: DynChunkPipeline<I, O, CI, CO>,
        scheduler: Arc<dyn SideEffectScheduler>,
        config: SideEffectHandlingConfig,
    ) -> Self {
        Self {
            sub,
            scheduler,
            config,
        }
    }
}

#[async_trait]
impl<I, O, CI, CO> ChunkPipeline<I, O, CI, CO> for SideEffectHandlingPipeline<I, O, CI, CO>
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
        let Some(mut results) = self.sub.next().await? else {
            return Ok(None);
        };
        let side_effects: Vec<SideEffect> = results
            .iter_mut()
            .flat_map(|r| std::mem::take(&mut r.context.side_effects))
            .collect();
        handle(self.scheduler.as_ref(), self.config, side_effects).await;
        Ok(Some(results))
    }
}

pub struct SideEffectHandlingProcessor<I, O, C> {
    sub: DynPipeline<I, O, C>,
    scheduler: Arc<dyn SideEffectScheduler>,
    config: SideEffectHandlingConfig,
}

impl<I, O, C> SideEffectHandlingProcessor<I, O, C> {
    pub fn new(
        sub: DynPipeline<I, O, C>,
        scheduler: Arc<dyn SideEffectScheduler>,
        config: SideEffectHandlingConfig,
    ) -> Self {
        Self {
            sub,
            scheduler,
            config,
        }
    }
}

#[async_trait]
impl<I, O, C> Pipeline<I, O, C> for SideEffectHandlingProcessor<I, O, C>
where
    I: Send + 'static,
    O: Send + 'static,
    C: Send + 'static,
{
    async fn process(
        &self,
        input: OkResultWithContext<I, C>,
    ) -> anyhow::Result<ResultWithContext<O, C>> {
        let mut result = self.sub.process(input).await?;
        let side_effects = std::mem::take(&mut result.context.side_effects);
        handle(self.scheduler.as_ref(), self.config, side_effects).await;
        Ok(result)
    }
}
