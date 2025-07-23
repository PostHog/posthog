import { Counter, Histogram, Summary } from 'prom-client'

import { logger } from '~/utils/logger'

// Deduplication operation counters
export const deduplicationOperationsTotal = new Counter({
    name: 'deduplication_operations_total',
    help: 'Total number of deduplication operations performed',
    labelNames: ['operation', 'outcome'],
})

// Duplicate detection tracking
export const duplicatesDetectedTotal = new Counter({
    name: 'duplicates_detected_total',
    help: 'Total number of duplicate events detected',
    labelNames: ['operation'],
})

// Events processed through deduplication
export const eventsProcessedTotal = new Counter({
    name: 'deduplication_events_processed_total',
    help: 'Total number of events processed through deduplication',
    labelNames: ['operation'],
})

// Duplicate breakdown by team and source
export const duplicateBreakdownTotal = new Counter({
    name: 'deduplication_breakdown_total',
    help: 'Total number of duplicate events broken down by source',
    labelNames: ['source'],
})

// Deduplication operation duration
export const deduplicationOperationDurationMs = new Summary({
    name: 'deduplication_operation_duration_ms',
    help: 'Duration of deduplication operations in milliseconds',
    labelNames: ['operation'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

// Batch size distribution
export const deduplicationBatchSize = new Histogram({
    name: 'deduplication_batch_size',
    help: 'Distribution of deduplication batch sizes',
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000],
})

export const deduplicationOperationOutcomesCounter = new Counter({
    name: 'deduplication_operation_outcomes_total',
    help: 'Total number of deduplication operation outcomes',
    labelNames: ['operation', 'outcome'],
})

export interface KeyMetricData {
    source: string
}

export function duplicateReport(duplicates: Set<string>, keyToMetricDataMap: Map<string, KeyMetricData>): void {
    // Group duplicates by team_id and source to batch metric increments
    const metricCounts = new Map<string, { labels: KeyMetricData; count: number }>()

    duplicates.forEach((duplicateKey) => {
        const metricData = keyToMetricDataMap.get(duplicateKey)
        if (metricData) {
            const key = metricData.source
            const existing = metricCounts.get(key)

            if (existing) {
                existing.count++
            } else {
                metricCounts.set(key, {
                    labels: { source: metricData.source },
                    count: 1,
                })
            }
        }
    })

    // log the metricCounts
    logger.info('deduplication metric breakdown', { metricCounts })

    // Batch increment metrics - one call per unique team_id/source combination
    metricCounts.forEach(({ labels, count }) => {
        duplicateBreakdownTotal.inc(labels, count)
    })
}

export function recordDeduplicationOperation(
    operation: 'deduplicate' | 'deduplicateIds',
    startTime: number,
    processed: number,
    duplicates: number | string[],
    outcome: 'success' | 'error' | 'disabled'
) {
    const duration = Date.now() - startTime
    const duplicateCount = Array.isArray(duplicates) ? duplicates.length : duplicates

    // Record operation
    deduplicationOperationsTotal.inc({ operation, outcome })

    if (outcome === 'success') {
        // Record timing
        deduplicationOperationDurationMs.observe({ operation }, duration)

        // Record batch size
        deduplicationBatchSize.observe(processed)

        // Record events processed and duplicates found
        eventsProcessedTotal.inc({ operation }, processed)
        duplicatesDetectedTotal.inc({ operation }, duplicateCount)

        deduplicationOperationOutcomesCounter.inc({ operation, outcome: 'success' })
    } else if (outcome === 'error') {
        deduplicationOperationOutcomesCounter.inc({ operation, outcome })
    } else if (outcome === 'disabled') {
        deduplicationOperationOutcomesCounter.inc({ operation, outcome })
    }
}
