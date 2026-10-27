import { Dayjs, dayjs } from 'lib/dayjs'

import type { DataCatalogMetricApi } from './generated/api.schemas'

const CLEANUP_AFTER_DAYS = 90

/** An approved metric that nobody ran for 90 days, and that is old enough for that to mean something. */
export function isCleanupCandidate(metric: DataCatalogMetricApi, now: Dayjs): boolean {
    if (metric.status !== 'approved' || metric.is_drifted) {
        return false
    }
    const cutoff = now.subtract(CLEANUP_AFTER_DAYS, 'day')
    if (!metric.created_at || dayjs(metric.created_at).isAfter(cutoff)) {
        return false
    }
    return !metric.last_run_at || dayjs(metric.last_run_at).isBefore(cutoff)
}
