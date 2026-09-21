import { ChunkProcessingStep } from '~/ingestion/framework/builders'
import { drop, ok } from '~/ingestion/framework/results'

import { metricMessageDroppedCounter } from './metrics'
import { MetricsUsageAccumulator } from './metrics-usage'
import { MetricsRateLimiterService } from './services/metrics-rate-limiter.service'
import { MetricsIngestionMessage } from './types'

/**
 * Token-bucket rate limiting is one Redis round trip per chunk, so this is a
 * chunk step: place it after `gather()` so the whole batch shares that trip.
 * Messages that pass are recorded as allowed usage here, before the produce,
 * so a message that later fails to produce is still billed as received.
 */
export function createRateLimitMetricsStep<T extends MetricsIngestionMessage & { usage: MetricsUsageAccumulator }>(
    rateLimiter: Pick<MetricsRateLimiterService, 'filterMessages'>
): ChunkProcessingStep<T, T> {
    return async function rateLimitMetricsStep(values) {
        const { dropped } = await rateLimiter.filterMessages(values)
        const droppedSet = new Set<T>(dropped)

        return values.map((value) => {
            if (droppedSet.has(value)) {
                value.usage.recordDropped(value.teamId, value.bytesUncompressed, value.recordCount)
                metricMessageDroppedCounter.inc({ reason: 'rate_limited', team_id: value.teamId.toString() })
                return drop<T>('rate_limited')
            }
            value.usage.recordAllowed(value.teamId, value.bytesUncompressed, value.recordCount)
            return ok(value)
        })
    }
}
