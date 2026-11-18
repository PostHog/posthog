import type { HogQLQuery } from '~/queries/schema/schema-general'

import type { ViewEngineApi, ViewEngineTargetEnumApi } from '../generated/api.schemas'

export const CONNECTION_SAVE_AS_VIEW_REASON =
    "Views can't be saved on a direct connection. Create the view in your own database, or save this query as an insight."

const AVAILABLE = { available: true, reason: null }

const CLICKHOUSE_ENGINE: ViewEngineApi = {
    target: 'clickhouse',
    dialect: 'hogql',
    connection_id: null,
    capabilities: {
        materialize: AVAILABLE,
        lineage: AVAILABLE,
        referenceable_from_clickhouse: AVAILABLE,
        column_source: 'clickhouse_probe',
    },
}

export function viewEngine(view: { engine?: ViewEngineApi }): ViewEngineApi {
    return view.engine ?? CLICKHOUSE_ENGINE
}

export function queryEngineTarget(
    source: Pick<HogQLQuery, 'executionTarget' | 'connectionId'>
): ViewEngineTargetEnumApi {
    if (source.executionTarget === 'managed_trino') {
        return 'managed_trino'
    }
    return source.connectionId ? 'connection' : 'clickhouse'
}

export function saveAsViewDisabledReason(source: Pick<HogQLQuery, 'executionTarget' | 'connectionId'>): string | null {
    return queryEngineTarget(source) === 'connection' ? CONNECTION_SAVE_AS_VIEW_REASON : null
}
