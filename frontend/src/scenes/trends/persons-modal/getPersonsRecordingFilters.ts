import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    RecordingUniversalFilters,
    UniversalFilterValue,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

// Scope session recordings to the funnel's selected breakdown value. Load-bearing:
// matched_recordings from the backend contains ALL of each actor's session IDs, so we
// need this filter to actually narrow the list. Returns null for breakdown types that
// can't be a single property filter (hogql / data_warehouse / multi-key / multi-value).

function buildFunnelBreakdownFilter(source: ActorsQuery['source'] | null): UniversalFilterValue | null {
    if (!source || source.kind !== NodeKind.FunnelsActorsQuery || source.funnelStepBreakdown == null) {
        return null
    }
    const breakdownFilter = source.source.breakdownFilter
    const breakdown = breakdownFilter?.breakdown
    const breakdownType = breakdownFilter?.breakdown_type ?? 'event'

    // Backend sends single values as one-element arrays (e.g. ["NL"]). Unwrap them; bail
    // for genuine multi-value arrays — a click represents one selected value.
    const rawBreakdownValue = source.funnelStepBreakdown
    let breakdownValue: string | number
    if (Array.isArray(rawBreakdownValue)) {
        if (rawBreakdownValue.length !== 1) {
            return null
        }
        breakdownValue = rawBreakdownValue[0]
    } else {
        breakdownValue = rawBreakdownValue
    }

    // Cohort → cohort membership filter. Skip the "All users" pseudo-cohort (0 / 'all').
    if (breakdownType === 'cohort') {
        if (breakdownValue === 0 || breakdownValue === 'all') {
            return null
        }
        const cohortId = typeof breakdownValue === 'number' ? breakdownValue : Number(breakdownValue)
        if (!Number.isFinite(cohortId)) {
            return null
        }
        return {
            type: PropertyFilterType.Cohort,
            key: 'id',
            value: cohortId,
            operator: PropertyOperator.In,
        }
    }

    // Non-cohort types need a single property key.
    if (!breakdown || Array.isArray(breakdown)) {
        return null
    }

    const key = String(breakdown)
    const base = { key, value: breakdownValue, operator: PropertyOperator.Exact }

    switch (breakdownType) {
        case 'event':
            return { ...base, type: PropertyFilterType.Event }
        case 'event_metadata':
            return { ...base, type: PropertyFilterType.EventMetadata }
        case 'person':
            return { ...base, type: PropertyFilterType.Person }
        case 'session':
            return { ...base, type: PropertyFilterType.Session }
        case 'group':
            if (breakdownFilter?.breakdown_group_type_index == null) {
                return null
            }
            return {
                ...base,
                type: PropertyFilterType.Group,
                group_type_index: breakdownFilter.breakdown_group_type_index,
            }
        // hogql / data_warehouse / revenue_analytics don't map to a single property filter.
        default:
            return null
    }
}

export const getPersonsRecordingFilters = (
    actorsQuery: ActorsQuery | null,
    sessionIds: string[]
): Partial<RecordingUniversalFilters> => {
    if (!actorsQuery || !actorsQuery.source) {
        return {}
    }

    const source = actorsQuery.source

    // Scope recordings to the selected funnel breakdown value (e.g. country = "NL").
    const funnelBreakdownFilter = buildFunnelBreakdownFilter(source)

    // The actual insight query (with series, properties, etc.) is nested at source.source
    let insightQuery = source
    if ('source' in source && source.source) {
        insightQuery = source.source as any
    }

    let date_from: string | undefined
    let date_to: string | undefined

    if ('dateRange' in insightQuery && insightQuery.dateRange) {
        const dateRange = insightQuery.dateRange as any
        date_from = dateRange.date_from || undefined
        date_to = dateRange.date_to || undefined
    }

    // If we have session IDs from matched_recordings, use them directly for efficient lookup
    if (sessionIds.length > 0) {
        return {
            session_ids: sessionIds,
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: funnelBreakdownFilter ? [funnelBreakdownFilter] : [],
                    },
                ],
            },
            duration: [],
            date_from,
            date_to,
        }
    }

    // For non-funnel queries or funnels without session IDs, use filter-based approach
    const filters: UniversalFilterValue[] = []

    // Extract events from the insight query series
    if ('series' in insightQuery && Array.isArray(insightQuery.series)) {
        // drop-off actors (negative funnelStep) only completed the steps before the
        // drop-off, so only those can be required as event filters
        let seriesToFilterOn: any[] = insightQuery.series
        if (source.kind === NodeKind.FunnelsActorsQuery && typeof source.funnelStep === 'number') {
            const completedStepCount = source.funnelStep > 0 ? source.funnelStep : Math.abs(source.funnelStep) - 1
            seriesToFilterOn = insightQuery.series.slice(0, completedStepCount)
        }
        seriesToFilterOn.forEach((series) => {
            let entityFilter: any = null
            if ('event' in series && series.event) {
                entityFilter = {
                    id: series.event,
                    name: series.event,
                    type: 'events',
                }
            } else if (series.kind === NodeKind.ActionsNode && series.id != null) {
                // action steps have an action id, not an event name
                entityFilter = {
                    id: series.id,
                    name: series.name,
                    type: 'actions',
                }
            }
            if (entityFilter) {
                if ('properties' in series && Array.isArray(series.properties) && series.properties.length > 0) {
                    entityFilter.properties = series.properties
                }
                filters.push(entityFilter)
            }
        })
    }

    // Add breakdown filter for funnels
    if (funnelBreakdownFilter) {
        filters.push(funnelBreakdownFilter)
    }

    // Add global properties from the insight query
    if ('properties' in insightQuery && Array.isArray(insightQuery.properties) && insightQuery.properties.length > 0) {
        filters.push(...insightQuery.properties)
    }

    // Build the result for non-funnel or fallback cases
    return {
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: filters,
                },
            ],
        },
        date_from,
        date_to,
    }
}
