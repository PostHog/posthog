import { EntityFilter, ActionFilter, FilterType, DashboardItemType, InsightShortId } from '~/types'
import { ensureStringIsNotBlank, objectsEqual } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/logics'

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
): Partial<DashboardItemType> | null {
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
