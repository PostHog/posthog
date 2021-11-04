import { EntityFilter, ActionFilter, FilterType, DashboardItemType } from '~/types'
import { ensureStringIsNotBlank, objectsEqual } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

export const getDisplayNameFromEntityFilter = (
    filter: EntityFilter | ActionFilter | null,
    isCustom = true
): string | null => {
    // Make sure names aren't blank strings
    const customName = ensureStringIsNotBlank(filter?.custom_name)
    const name = ensureStringIsNotBlank(filter?.name)

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
        // @ts-ignore
        if (!objectsEqual(value, oldObj[key])) {
            if (key === 'events') {
                if (value.length !== oldObj.events?.length) {
                    changedKeys['changed_events_length'] = oldObj.events?.length
                } else {
                    value.forEach((event: Record<string, any>, idx: number) => {
                        // @ts-ignore
                        const _k = extractObjectDiffKeys(oldObj[key][idx], event, `event_${idx}_`)
                        changedKeys = {
                            ...changedKeys,
                            ..._k,
                        }
                    })
                }
            } else if (key === 'actions') {
                if (value.length !== oldObj.actions?.length) {
                    changedKeys['changed_actions_length'] = oldObj.actions?.length
                } else {
                    value.forEach((action: Record<string, any>, idx: number) => {
                        // @ts-ignore
                        const _k = extractObjectDiffKeys(oldObj[key][idx], action, `action_${idx}_`)
                        changedKeys = {
                            ...changedKeys,
                            ..._k,
                        }
                    })
                }
            } else {
                // @ts-ignore
                changedKeys[`changed_${prefix}${key}`] = oldObj[key]
            }
        }
    }

    return changedKeys
}

export function findInsightFromMountedLogic(
    insightId: number,
    dashboardId: number | undefined
): Partial<DashboardItemType> | null {
    if (dashboardId) {
        const insight = dashboardLogic
            .findMounted({ id: dashboardId })
            ?.values.allItems?.items?.find((item) => item.id === insightId)
        if (insight) {
            return insight
        }
    }

    const insight2 = savedInsightsLogic.findMounted()?.values.insights?.results?.find((item) => item.id === insightId)
    if (insight2) {
        return insight2
    }

    return null
}
