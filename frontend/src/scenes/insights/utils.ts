import { BuiltLogic, Logic } from 'kea'
import { ActionFilter, DashboardItemLogicProps, EntityFilter, InsightType, ViewType } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export const getLogicFromInsight = (
    insight: InsightType | undefined,
    logicProps: DashboardItemLogicProps
): Logic & BuiltLogic => {
    if (insight === ViewType.FUNNELS) {
        return funnelLogic(logicProps)
    } else if (insight === ViewType.RETENTION) {
        return retentionTableLogic(logicProps)
    } else if (insight === ViewType.PATHS) {
        return pathsLogic(logicProps)
    } else {
        return trendsLogic(logicProps)
    }
}

export const getDisplayNameFromEntityFilter = (
    filter: EntityFilter | ActionFilter | null,
    isCustom = true
): string | null => {
    const customName = (filter?.custom_name ?? '').trim() === '' ? null : filter?.custom_name

    return (isCustom ? customName : null) ?? filter?.name ?? (filter?.id ? `${filter?.id}` : null)
}
