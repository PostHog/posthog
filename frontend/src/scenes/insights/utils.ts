import { BuiltLogic, Logic } from 'kea'
import { SharedInsightLogicProps, InsightType, ViewType } from '~/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export const getLogicFromInsight = (
    insight: InsightType | undefined,
    logicProps: SharedInsightLogicProps
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
