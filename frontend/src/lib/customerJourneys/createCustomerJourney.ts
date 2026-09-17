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
    journey_name: 'dashboard_refresh' | 'experiment_refresh' | 'replay_open'
    resource_type: 'dashboard' | 'experiment' | 'session_recording'
    resource_id: string | number
    trigger: 'initial_load' | 'manual_refresh' | 'navigation' | 'retry'
    readiness_contract_version: number
    readiness_scope: 'visible_product_analytics_tiles' | 'modern_experiment_results' | 'player_mount_to_first_frame'
    attempt_id?: string
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
}

export interface CustomerJourneyInsightTypeSummary {
    total_count: number
    ready_count: number
    failed_count: number
    max_duration_ms?: number
}

export interface CustomerJourneySummary {
    exposures_response_cached?: boolean
    excluded_count?: number
    insight_type_summary?: Partial<Record<CustomerJourneyInsightType, CustomerJourneyInsightTypeSummary>>
    error_type?: 'query_error' | 'load_error' | 'playback_error' | 'timeout' | 'unknown'
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
            const counts: Record<string, number> = {}
            for (const key of [
                'total_count',
                'ready_count',
                'failed_count',
                'pending_count',
                'excluded_count',
            ] as const) {
                const value = summary[key]
                if (value !== undefined && Number.isSafeInteger(value) && value >= 0) {
                    counts[key] = value
                }
            }
            const insightTypeSummary: CustomerJourneySummary['insight_type_summary'] = {}
            for (const insightType of ['TRENDS', 'STICKINESS', 'LIFECYCLE', 'FUNNELS', 'RETENTION', 'PATHS'] as const) {
                const entry = summary.insight_type_summary?.[insightType]
                if (
                    entry &&
                    [entry.total_count, entry.ready_count, entry.failed_count].every(
                        (value) => Number.isSafeInteger(value) && value >= 0
                    )
                ) {
                    insightTypeSummary[insightType] = {
                        total_count: entry.total_count,
                        ready_count: entry.ready_count,
                        failed_count: entry.failed_count,
                        ...(entry.max_duration_ms !== undefined &&
                        Number.isFinite(entry.max_duration_ms) &&
                        entry.max_duration_ms >= 0
                            ? { max_duration_ms: entry.max_duration_ms }
                            : {}),
                    }
                }
            }
            let tileResults: CustomerJourneyTileResult[] | undefined
            let tileResultsTruncated: boolean | undefined
            if (summary.tile_results !== undefined) {
                const validInsightTypes = new Set<CustomerJourneyInsightType>([
                    'TRENDS',
                    'STICKINESS',
                    'LIFECYCLE',
                    'FUNNELS',
                    'RETENTION',
                    'PATHS',
                ])
                const validStates = new Set<CustomerJourneyTileState>(['ready', 'failed', 'pending'])
                const seenTileIds = new Set<number>()
                const sourceRows: unknown[] = Array.isArray(summary.tile_results) ? summary.tile_results : []
                tileResultsTruncated = summary.tile_results_truncated === true || !Array.isArray(summary.tile_results)
                tileResults = []
                for (const value of sourceRows) {
                    const row = value as Partial<CustomerJourneyTileResult> | null
                    const tileId = row?.tile_id
                    const insightShortId = row?.insight_short_id
                    const insightType = row?.insight_type
                    const state = row?.state
                    const duration = row?.duration_ms
                    const validDuration =
                        state !== 'ready' ||
                        (typeof duration === 'number' && Number.isFinite(duration) && duration >= 0)
                    if (
                        !row ||
                        typeof tileId !== 'number' ||
                        !Number.isSafeInteger(tileId) ||
                        tileId < 0 ||
                        typeof insightShortId !== 'string' ||
                        insightShortId.trim().length === 0 ||
                        insightShortId.length > 128 ||
                        !validInsightTypes.has(insightType as CustomerJourneyInsightType) ||
                        !validStates.has(state as CustomerJourneyTileState) ||
                        !validDuration ||
                        seenTileIds.has(tileId)
                    ) {
                        tileResultsTruncated = true
                        continue
                    }
                    seenTileIds.add(tileId)
                    tileResults.push({
                        tile_id: tileId,
                        insight_short_id: insightShortId,
                        insight_type: insightType as CustomerJourneyInsightType,
                        state: state as CustomerJourneyTileState,
                        ...(state === 'ready' ? { duration_ms: duration as number } : {}),
                    })
                }
                tileResults.sort((a, b) => a.tile_id - b.tile_id)
                if (tileResults.length > CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT) {
                    tileResultsTruncated = true
                    tileResults = tileResults.slice(0, CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT)
                }
            }
            capture('customer_journey_finished', {
                ...common,
                visibility_state: visibilityState,
                outcome,
                duration_ms: Math.max(0, finishedAt - startedAt),
                foreground_duration_ms: foregroundDurationMs,
                ...(firstUsefulMs !== undefined ? { first_useful_ms: firstUsefulMs } : {}),
                ...(summary.error_type !== undefined ? { error_type: summary.error_type } : {}),
                ...(summary.end_reason !== undefined ? { end_reason: summary.end_reason } : {}),
                ...counts,
                ...(typeof summary.exposures_response_cached === 'boolean'
                    ? { exposures_response_cached: summary.exposures_response_cached }
                    : {}),
                ...(Object.keys(insightTypeSummary).length ? { insight_type_summary: insightTypeSummary } : {}),
                ...(tileResults !== undefined
                    ? { tile_results: tileResults, tile_results_truncated: tileResultsTruncated }
                    : {}),
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
