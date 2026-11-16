import { NodeApiSuspended, NodeSuspensionApi } from './generated/api.schemas'

/**
 * Markers are written per engine, but only ClickHouse serves queries. A marker on the duckgres
 * shadow means the comparison run stopped, not that the model stopped refreshing.
 */
export const SERVING_ENGINE = 'clickhouse'

export function servingSuspension(suspended: NodeApiSuspended | undefined | null): NodeSuspensionApi | undefined {
    return suspended?.[SERVING_ENGINE]
}

/**
 * "Suspended" is PostHog stopping the schedule after repeated failures. "Paused" is the user
 * setting the cadence to never. The two states offer different actions, so the copy keeps the
 * two words apart.
 */
export function suspendedScheduleMessage(subject: 'view' | 'endpoint'): string {
    return `Scheduled runs are suspended for this ${subject} because materialization kept failing. Fix the query, then resume.`
}
