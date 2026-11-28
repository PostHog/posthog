import { Item, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (insightDataLoading) {
        return null
    }
    const warning = ((insightDataRaw as AnalyticsQueryResponseBase | null)?.warnings ?? []).find(
        (candidate): candidate is BreakdownNotAppliedWarning => candidate.type === 'breakdown_not_applied'
    )
    if (!warning) {
        return null
    }
    if (todayRailNav) {
        return (
            <div className="p-2">
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>{warning.message}</ItemDescription>
                    </ItemContent>
                </Item>
            </div>
        )
    }
    return (
        <LemonBanner type="info" className="mx-2 mb-2">
            {warning.message}
        </LemonBanner>
    )
}
