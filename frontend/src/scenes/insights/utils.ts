import { EntityFilter, ActionFilter, FilterType, InsightModel, InsightShortId, InsightType, PathType } from '~/types'
import { ensureStringIsNotBlank, objectsEqual } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/logics'
import { groupsModelType } from '~/models/groupsModelType'
import { toLocalFilters } from './ActionFilter/entityFilterLogic'
import { RETENTION_FIRST_TIME } from 'lib/constants'
import { retentionOptions } from 'scenes/retention/retentionTableLogic'

export const getDisplayNameFromEntityFilter = (
    filter: EntityFilter | ActionFilter | null,
    isCustom = true
): string | null => {
    // Make sure names aren't blank strings
    const customName = ensureStringIsNotBlank(filter?.custom_name)
    let name = ensureStringIsNotBlank(filter?.name)
    if (name && keyMapping.event[name]) {
        name = keyMapping.event[name].label
    }

    // Return custom name. If that doesn't exist then the name, then the id, then just null.
    return (isCustom ? customName : null) ?? name ?? (filter?.id ? `${filter?.id}` : null)
}

export function extractObjectDiffKeys(
    oldObj: Partial<FilterType>,
    newObj: Partial<FilterType>,
    prefix: string = ''
): Record<string, any> {
    if (Object.keys(oldObj).length === 0) {
        return []
    }

    let changedKeys: Record<string, any> = {}
    for (const [key, value] of Object.entries(newObj)) {
        const valueOrArray = value || []
        const oldValue = (oldObj as Record<string, any>)[key] || []
        if (!objectsEqual(value, oldValue)) {
            if (key === 'events') {
                if (valueOrArray.length !== oldValue.length) {
                    changedKeys['changed_events_length'] = oldValue?.length
                } else {
                    valueOrArray.forEach((event: Record<string, any>, idx: number) => {
                        changedKeys = {
                            ...changedKeys,
                            ...extractObjectDiffKeys(oldValue[idx], event, `event_${idx}_`),
                        }
                    })
                }
            } else if (key === 'actions') {
                if (valueOrArray.length !== oldValue.length) {
                    changedKeys['changed_actions_length'] = oldValue.length
                } else {
                    valueOrArray.forEach((action: Record<string, any>, idx: number) => {
                        changedKeys = {
                            ...changedKeys,
                            ...extractObjectDiffKeys(oldValue[idx], action, `action_${idx}_`),
                        }
                    })
                }
            } else {
                changedKeys[`changed_${prefix}${key}`] = oldValue
            }
        }
    }

    return changedKeys
}

export function findInsightFromMountedLogic(
    insightShortId: InsightShortId,
    dashboardId: number | undefined
): Partial<InsightModel> | null {
    if (dashboardId) {
        const insight = dashboardLogic
            .findMounted({ id: dashboardId })
            ?.values.allItems?.items?.find((item) => item.short_id === insightShortId)
        if (insight) {
            return insight
        }
    }

    const insight2 = savedInsightsLogic
        .findMounted()
        ?.values.insights?.results?.find((item) => item.short_id === insightShortId)
    if (insight2) {
        return insight2
    }

    return null
}

export async function getInsightId(shortId: InsightShortId): Promise<number | undefined> {
    return (await api.get(`api/projects/${getCurrentTeamId()}/insights/?short_id=${encodeURIComponent(shortId)}`))
        .results[0]?.id
}

function summarizePaths(filters: Partial<FilterType>): string {
    // Sync with PathsSummary in InsightDetails
    let humanEventTypes: string[] = []
    if (filters.include_event_types) {
        let matchCount = 0
        if (filters.include_event_types.includes(PathType.PageView)) {
            humanEventTypes.push('page views')
            matchCount++
        }
        if (filters.include_event_types.includes(PathType.Screen)) {
            humanEventTypes.push('screen views')
            matchCount++
        }
        if (filters.include_event_types.includes(PathType.CustomEvent)) {
            humanEventTypes.push('custom events')
            matchCount++
        }
        if (matchCount === 0 || matchCount === 3) {
            humanEventTypes = ['all events']
        }
    }
    let summary = `User paths based on ${humanEventTypes.join(' and ')}`
    if (filters.start_point) {
        summary += ` starting at ${filters.start_point}`
    }
    if (filters.end_point) {
        summary += ` ending at ${filters.end_point}`
    }
    return summary
}

export function summarizeInsightFilters(
    filters: Partial<FilterType>,
    aggregationLabel: groupsModelType['values']['aggregationLabel']
): string {
    const insightType = filters.insight
    if (insightType === InsightType.RETENTION) {
        const areTargetAndReturningIdentical =
            filters.returning_entity?.id === filters.target_entity?.id &&
            filters.returning_entity?.type === filters.target_entity?.type
        return (
            `Retention of ${aggregationLabel(filters.aggregation_group_type_index).plural}` +
            ` based on doing ${getDisplayNameFromEntityFilter((filters.target_entity || {}) as EntityFilter)}` +
            ` ${retentionOptions[filters.retention_type || RETENTION_FIRST_TIME]} and coming back with ` +
            (areTargetAndReturningIdentical
                ? 'the same event'
                : getDisplayNameFromEntityFilter((filters.returning_entity || {}) as EntityFilter))
        )
    } else if (insightType === InsightType.PATHS) {
        return summarizePaths(filters)
    } else {
        const localFilters = toLocalFilters(filters)
        console.log(localFilters)
        if (insightType === InsightType.LIFECYCLE) {
            return `User lifecycle based on ${getDisplayNameFromEntityFilter(localFilters[0])}`
        }
        return 'Foo'
    }
}
