import { NodeApiSuspended, NodeSuspensionApi } from './generated/api.schemas'

/**
 * Markers are written per engine, but only ClickHouse serves queries. A marker on the duckgres
 * shadow means the comparison run stopped, not that the model stopped refreshing.
 */
export const SERVING_ENGINE = 'clickhouse'

export function servingSuspension(suspended: NodeApiSuspended | undefined | null): NodeSuspensionApi | undefined {
    return suspended?.[SERVING_ENGINE]
}
