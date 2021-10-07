import { BuiltLogic, Logic } from 'kea'
import { InsightLogicProps, InsightType, ViewType, EntityFilter, ActionFilter } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ensureStringIsNotBlank } from 'lib/utils'

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
