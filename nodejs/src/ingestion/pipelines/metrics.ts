import { Counter, Histogram, exponentialBuckets } from 'prom-client'

export const sideEffectResultCounter = new Counter({
    name: 'pipelines_side_effects_total',
    help: 'Total number of side effects processed with their results',
    labelNames: ['result'],
})

export const pipelineStepDurationHistogram = new Histogram({
    name: 'ingestion_pipeline_step_duration_seconds',
    help: 'Duration of pipeline step execution',
    labelNames: ['step_name', 'step_type', 'result'],
    buckets: exponentialBuckets(0.001, 2, 15), // 1ms -> ~16s
})
