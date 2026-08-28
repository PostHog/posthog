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

export const pipelineRetryAttemptsHistogram = new Histogram({
    name: 'ingestion_pipeline_retry_attempts',
    help: 'Attempts a retrying pipeline wrapper made before completing, exhausting retries, or hitting a non-retriable error',
    labelNames: ['name', 'outcome'],
    buckets: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
})

export const batchBudgetExhaustedCounter = new Counter({
    name: 'ingestion_batch_budget_exhausted_total',
    help: 'Batch budgets that expired before their batch completed',
})

export const batchBudgetOverrunHistogram = new Histogram({
    name: 'ingestion_batch_budget_overrun_seconds',
    help: 'Time from a batch budget expiring to its batch completing: the tail the checkpoints cannot cut',
    buckets: exponentialBuckets(0.01, 2, 12), // 10ms -> ~40s
})

export const batchBudgetCheckpointCounter = new Counter({
    name: 'ingestion_batch_budget_checkpoint_total',
    help: 'Elements a budget checkpoint cut off, by checkpoint and step',
    labelNames: ['checkpoint', 'step_name'],
})

/** Where a budget checkpoint sits: before an element step or before a chunk step. */
export type BudgetCheckpoint = 'step' | 'chunk'

export function recordBudgetCheckpoint(checkpoint: BudgetCheckpoint, stepName: string): void {
    batchBudgetCheckpointCounter.labels({ checkpoint, step_name: stepName }).inc()
}
