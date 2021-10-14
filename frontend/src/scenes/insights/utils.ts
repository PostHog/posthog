import { BuiltLogic, Logic } from 'kea'
import { InsightLogicProps, InsightType, ViewType, EntityFilter, ActionFilter, FilterType } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ensureStringIsNotBlank, objectsEqual } from 'lib/utils'

export const getLogicFromInsight = (
    insight: InsightType | undefined,
    insightProps: InsightLogicProps
): Logic & BuiltLogic => {
    if (insight === ViewType.FUNNELS) {
        return funnelLogic(insightProps)
    } else if (insight === ViewType.RETENTION) {
        return retentionTableLogic(insightProps)
    } else if (insight === ViewType.PATHS) {
        return pathsLogic(insightProps)
    } else {
        return trendsLogic(insightProps)
    }
}

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
