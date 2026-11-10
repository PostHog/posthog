import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { useWebTileInsightData } from 'scenes/web-analytics/webTileHeaderHooks'

import { AnalyticsQueryResponseBase, BreakdownNotAppliedWarning } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

export function MarketingCostBreakdownWarning({
    insightProps,
}: {
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const { insightDataRaw, insightDataLoading } = useWebTileInsightData(insightProps)
    if (insightDataLoading) {
        return null
    }
    const warning = ((insightDataRaw as AnalyticsQueryResponseBase | null)?.warnings ?? []).find(
        (candidate): candidate is BreakdownNotAppliedWarning => candidate.type === 'breakdown_not_applied'
    )
    if (!warning) {
        return null
    }
    return (
        <LemonBanner type="info" className="mx-2 mb-2">
            {warning.message}
        </LemonBanner>
    )
}
