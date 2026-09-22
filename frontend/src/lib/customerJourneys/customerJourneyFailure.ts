import { CLICKHOUSE_MEMORY_LIMIT_ERROR_CODE } from 'lib/api-error'

import type { CustomerJourneySummary } from './createCustomerJourney'

export function customerJourneyFailure(
    error: unknown,
    fallback: 'query_error' | 'load_error' = 'query_error'
): { outcome: 'failed' | 'timed_out'; error_type: NonNullable<CustomerJourneySummary['error_type']> } {
    const failure = error as { status?: unknown; code?: unknown } | null | undefined
    if (failure?.code === CLICKHOUSE_MEMORY_LIMIT_ERROR_CODE || failure?.status === 513) {
        return { outcome: 'failed', error_type: 'out_of_memory' }
    }
    if (failure?.status === 504) {
        // This may be a gateway timeout; it does not prove ClickHouse reached its execution limit.
        return { outcome: 'timed_out', error_type: 'timeout' }
    }
    if (failure?.status === 512) {
        // The query was rejected as too expensive, rather than executing and timing out.
        return { outcome: 'failed', error_type: 'query_rejected' }
    }
    return { outcome: 'failed', error_type: fallback }
}
