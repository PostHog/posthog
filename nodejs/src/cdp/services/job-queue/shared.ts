import { Counter, Gauge } from 'prom-client'

import { CyclotronJobQueueKind, CyclotronJobQueueSource } from '../../types'

const cdpCyclotronBatchUtilization = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue', 'source'],
})

const cdpCyclotronJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue', 'source'],
})

/**
 * Records throughput and batch utilization for a consumed batch.
 * `cdp_cyclotron_batch_utilization` is consumed by KEDA to autoscale the cyclotron workers, so this
 * must be called on every batch — including empty ones — so idle workers report zero and can scale down.
 */
export function observeConsumedBatch(params: {
    queue: CyclotronJobQueueKind
    source: CyclotronJobQueueSource
    batchSize: number
    maxBatchSize: number
}): void {
    const { queue, source, batchSize, maxBatchSize } = params
    cdpCyclotronBatchUtilization.labels({ queue, source }).set(maxBatchSize > 0 ? batchSize / maxBatchSize : 0)
    cdpCyclotronJobsProcessed.inc({ queue, source }, batchSize)
}
