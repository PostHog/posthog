export type CustomerJourneyOutcome =
    | 'usable'
    | 'failed'
    | 'timed_out'
    | 'cancelled'
    | 'superseded'
    | 'exited'
    | 'observation_stopped'

export type CustomerJourneyEndReason = 'cancelled' | 'superseded' | 'exited' | 'observation_stopped'

export interface CustomerJourneyOptions {
    journey_name:
        | 'dashboard_open'
        | 'dashboard_refresh'
        | 'experiment_refresh'
        | 'replay_open'
        | 'person_search'
        | 'sql_run'
    resource_type: 'dashboard' | 'experiment' | 'session_recording' | 'persons' | 'sql_editor'
    resource_id: string | number
    trigger: 'initial_load' | 'manual_refresh' | 'automatic_refresh' | 'navigation' | 'retry' | 'query_execution'
    readiness_contract_version: number
    readiness_scope:
        | 'visible_product_analytics_tiles'
        | 'modern_experiment_results'
        | 'player_mount_to_first_frame'
        | 'persons_list_query_to_table_commit'
        | 'sql_query_to_results_commit'
    attempt_id?: string
    client_query_id?: string
    execution_path?: 'per_metric' | 'recalculation'
    workload_class?: 'unknown'
}

export interface CustomerJourneyContext extends CustomerJourneyOptions {
    attempt_id: string
    region: 'US' | 'EU'
    project_id: number
    organization_id: string
    registry_version: string
}

export type CustomerJourneyInsightType = 'TRENDS' | 'STICKINESS' | 'LIFECYCLE' | 'FUNNELS' | 'RETENTION' | 'PATHS'
export type CustomerJourneyTileState = 'ready' | 'failed' | 'pending'

export const CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT = 50

export interface CustomerJourneyTileResult {
    tile_id: number
    insight_short_id: string
    insight_type: CustomerJourneyInsightType
    state: CustomerJourneyTileState
    duration_ms?: number
    client_query_id?: string
    response_cached?: boolean
}

export interface CustomerJourneyInsightTypeSummary {
    total_count: number
    ready_count: number
    failed_count: number
    max_duration_ms?: number
}

export interface CustomerJourneySummary {
    response_cached?: boolean
    experiment_run_id?: string
    exposures_response_cached?: boolean
    excluded_count?: number
    insight_type_summary?: Partial<Record<CustomerJourneyInsightType, CustomerJourneyInsightTypeSummary>>
    error_type?:
        | 'query_error'
        | 'load_error'
        | 'playback_error'
        | 'timeout'
        | 'out_of_memory'
        | 'query_rejected'
        | 'unknown'
    end_reason?: CustomerJourneyEndReason
    total_count?: number
    ready_count?: number
    failed_count?: number
    pending_count?: number
    tile_results?: CustomerJourneyTileResult[]
    tile_results_truncated?: boolean
}

export interface CustomerJourney {
    readonly attemptId: string
    firstUseful: () => void
    finish: (outcome: CustomerJourneyOutcome, summary?: CustomerJourneySummary) => void
    dispose: (reason: CustomerJourneyEndReason) => void
}

export interface CustomerJourneyDependencies {
    now: () => number
    capture: (
        event: 'customer_journey_started' | 'customer_journey_finished',
        properties: Record<string, unknown>
    ) => boolean | void
    visibility: {
        getState: () => DocumentVisibilityState
        subscribe: (listener: () => void) => () => void
    }
}

const CUSTOMER_JOURNEY_INSIGHT_TYPES: readonly CustomerJourneyInsightType[] = [
    'TRENDS',
    'STICKINESS',
    'LIFECYCLE',
    'FUNNELS',
    'RETENTION',
    'PATHS',
]
const CUSTOMER_JOURNEY_TILE_STATES: readonly CustomerJourneyTileState[] = ['ready', 'failed', 'pending']
const CUSTOMER_JOURNEY_SUMMARY_COUNT_KEYS = [
    'total_count',
    'ready_count',
    'failed_count',
    'pending_count',
    'excluded_count',
] as const

interface ProjectedTileResults {
    tile_results: CustomerJourneyTileResult[]
    tile_results_truncated: boolean
}

function isNonnegativeSafeInteger(value: unknown): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isNonnegativeFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

function isCustomerJourneyInsightType(value: unknown): value is CustomerJourneyInsightType {
    return CUSTOMER_JOURNEY_INSIGHT_TYPES.includes(value as CustomerJourneyInsightType)
}

function isCustomerJourneyTileState(value: unknown): value is CustomerJourneyTileState {
    return CUSTOMER_JOURNEY_TILE_STATES.includes(value as CustomerJourneyTileState)
}

function projectSummaryCounts(summary: CustomerJourneySummary): Record<string, number> {
    const counts: Record<string, number> = {}
    for (const key of CUSTOMER_JOURNEY_SUMMARY_COUNT_KEYS) {
        const value = summary[key]
        if (isNonnegativeSafeInteger(value)) {
            counts[key] = value
        }
    }
    return counts
}

function projectInsightTypeSummary(
    summary: CustomerJourneySummary
): NonNullable<CustomerJourneySummary['insight_type_summary']> {
    const projected: NonNullable<CustomerJourneySummary['insight_type_summary']> = {}
    for (const insightType of CUSTOMER_JOURNEY_INSIGHT_TYPES) {
        const entry = summary.insight_type_summary?.[insightType]
        if (entry && [entry.total_count, entry.ready_count, entry.failed_count].every(isNonnegativeSafeInteger)) {
            projected[insightType] = {
                total_count: entry.total_count,
                ready_count: entry.ready_count,
                failed_count: entry.failed_count,
                ...(isNonnegativeFiniteNumber(entry.max_duration_ms) ? { max_duration_ms: entry.max_duration_ms } : {}),
            }
        }
    }
    return projected
}

function projectTileResult(value: unknown, seenTileIds: Set<number>): CustomerJourneyTileResult | null {
    const row = value as Partial<CustomerJourneyTileResult> | null
    const tileId = row?.tile_id
    const insightShortId = row?.insight_short_id
    const insightType = row?.insight_type
    const state = row?.state
    const duration = row?.duration_ms
    if (
        !row ||
        !isNonnegativeSafeInteger(tileId) ||
        typeof insightShortId !== 'string' ||
        insightShortId.trim().length === 0 ||
        insightShortId.length > 128 ||
        !isCustomerJourneyInsightType(insightType) ||
        !isCustomerJourneyTileState(state) ||
        (state === 'ready' && !isNonnegativeFiniteNumber(duration)) ||
        seenTileIds.has(tileId)
    ) {
        return null
    }
    seenTileIds.add(tileId)
    return {
        tile_id: tileId,
        insight_short_id: insightShortId,
        insight_type: insightType,
        state,
        ...(state === 'ready' ? { duration_ms: duration as number } : {}),
        ...(typeof row.client_query_id === 'string' && row.client_query_id.length <= 128
            ? { client_query_id: row.client_query_id }
            : {}),
        ...(typeof row.response_cached === 'boolean' ? { response_cached: row.response_cached } : {}),
    }
}

function projectTileResults(summary: CustomerJourneySummary): ProjectedTileResults | undefined {
    if (summary.tile_results === undefined) {
        return undefined
    }

    const sourceRows: unknown[] = Array.isArray(summary.tile_results) ? summary.tile_results : []
    let truncated = summary.tile_results_truncated === true || !Array.isArray(summary.tile_results)
    const seenTileIds = new Set<number>()
    const tileResults: CustomerJourneyTileResult[] = []
    for (const value of sourceRows) {
        const projected = projectTileResult(value, seenTileIds)
        if (projected) {
            tileResults.push(projected)
        } else {
            truncated = true
        }
    }
    tileResults.sort((a, b) => a.tile_id - b.tile_id)
    return {
        tile_results: tileResults.slice(0, CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT),
        tile_results_truncated: truncated || tileResults.length > CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT,
    }
}

function projectCustomerJourneySummary(summary: CustomerJourneySummary): Record<string, unknown> {
    const insightTypeSummary = projectInsightTypeSummary(summary)
    const tileResults = projectTileResults(summary)
    return {
        ...(summary.error_type !== undefined ? { error_type: summary.error_type } : {}),
        ...(summary.end_reason !== undefined ? { end_reason: summary.end_reason } : {}),
        ...projectSummaryCounts(summary),
        ...(typeof summary.response_cached === 'boolean' ? { response_cached: summary.response_cached } : {}),
        ...(typeof summary.experiment_run_id === 'string' && summary.experiment_run_id.length <= 128
            ? { experiment_run_id: summary.experiment_run_id }
            : {}),
        ...(typeof summary.exposures_response_cached === 'boolean'
            ? { exposures_response_cached: summary.exposures_response_cached }
            : {}),
        ...(Object.keys(insightTypeSummary).length ? { insight_type_summary: insightTypeSummary } : {}),
        ...tileResults,
    }
}

export function createCustomerJourney(
    context: CustomerJourneyContext,
    { now, capture, visibility }: CustomerJourneyDependencies
): CustomerJourney | null {
    const startedAt = now()
    let visibilityState = visibility.getState()
    const common = {
        schema_version: 1,
        journey_name: context.journey_name,
        attempt_id: context.attempt_id,
        region: context.region,
        project_id: context.project_id,
        organization_id: context.organization_id,
        resource_type: context.resource_type,
        resource_id: context.resource_id,
        trigger: context.trigger,
        readiness_contract_version: context.readiness_contract_version,
        registry_version: context.registry_version,
        readiness_scope: context.readiness_scope,
        ...(context.client_query_id !== undefined ? { client_query_id: context.client_query_id } : {}),
        ...(context.execution_path !== undefined ? { execution_path: context.execution_path } : {}),
        ...(context.workload_class !== undefined ? { workload_class: context.workload_class } : {}),
    }
    try {
        // Pinned event names: changes break the start/finish join used by journey reports.
        if (capture('customer_journey_started', { ...common, visibility_state: visibilityState }) === false) {
            return null
        }
    } catch {
        return null
    }

    let finished = false
    let firstUsefulMs: number | undefined
    let foregroundDurationMs = 0
    let lastObservedAt = startedAt
    const accumulateForeground = (): number => {
        const time = now()
        if (visibilityState === 'visible') {
            foregroundDurationMs += Math.max(0, time - lastObservedAt)
        }
        lastObservedAt = time
        visibilityState = visibility.getState()
        return time
    }
    const unsubscribe = visibility.subscribe(() => {
        if (!finished) {
            accumulateForeground()
        }
    })

    const finish = (outcome: CustomerJourneyOutcome, summary: CustomerJourneySummary = {}): void => {
        if (finished) {
            return
        }
        finished = true
        try {
            const finishedAt = accumulateForeground()
            capture('customer_journey_finished', {
                ...common,
                visibility_state: visibilityState,
                outcome,
                duration_ms: Math.max(0, finishedAt - startedAt),
                foreground_duration_ms: foregroundDurationMs,
                ...(firstUsefulMs !== undefined ? { first_useful_ms: firstUsefulMs } : {}),
                ...projectCustomerJourneySummary(summary),
            })
        } catch {
            // Telemetry must not interrupt the operation it observes.
        } finally {
            unsubscribe()
        }
    }
    return {
        attemptId: common.attempt_id,
        firstUseful: () => {
            if (!finished && firstUsefulMs === undefined) {
                firstUsefulMs = Math.max(0, now() - startedAt)
            }
        },
        finish,
        dispose: (reason) => finish(reason, { end_reason: reason }),
    }
}
