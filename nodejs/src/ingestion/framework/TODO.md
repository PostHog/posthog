# Pipeline redirect outputs — remaining items

## Done

- ~~Casts in step-pipeline.ts and base-batch-pipeline.ts~~ — removed
- ~~Feed refactor~~ — feed() only accepts OkResultWithContext
- ~~as-any casts in test feed() calls~~ — removed, use createMockPipeline instead
- ~~Doc comments for R parameter~~ — added to PipelineResult, Pipeline, ProcessingStep, BatchProcessingStep
- ~~Living docs updated~~ — 01-introduction and 07-result-handling reflect named outputs
- ~~Dead config cleanup~~ — removed overflowTopic from subpipeline configs, PERSON_MERGE_ASYNC_TOPIC from options

## Remaining (low priority)

### Type wideness

- `tophog.ts` — `TopHogMetric.start` callback uses `PipelineResult<TOutput, string>`. Metrics are consumers so `string` is semantically correct, but inconsistent with `never` defaults elsewhere.
- `gathering-batch-pipeline.test.ts` — mock class uses `any` types. Should be properly typed.
