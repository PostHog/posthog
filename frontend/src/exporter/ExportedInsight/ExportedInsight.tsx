import { ChartDisplayType, InsightLogicProps, InsightModel, InsightType } from '~/types'
import React from 'react'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightViz } from 'lib/components/InsightCard/InsightCard'
import './ExportedInsight.scss'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { dateFilterToText } from 'lib/utils'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'

export function ExportedInsight({
    insight,
    showLogo = true,
}: {
    insight: InsightModel
    showLogo?: boolean
}): JSX.Element {
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        cachedInsight: insight,
        doNotLoad: true,
    }

    const { filters, name, derived_name, description } = insight

    const showLegend =
        filters.insight === InsightType.TRENDS &&
        filters.display !== ChartDisplayType.WorldMap &&
        filters.display !== ChartDisplayType.ActionsTable

    return (
        <BindLogic logic={insightLogic} props={insightLogicProps}>
            <div className="ExportedInsight">
                <div className="ExportedInsight-header">
                    <div>
                        <h5>
                            <span title={INSIGHT_TYPES_METADATA[filters.insight || InsightType.TRENDS]?.description}>
                                {INSIGHT_TYPES_METADATA[filters.insight || InsightType.TRENDS]?.name}
                            </span>{' '}
                            • {dateFilterToText(filters.date_from, filters.date_to, 'Last 7 days')}
                        </h5>
                        <h4 title={name} className="ExportedInsight-header-title">
                            {name || derived_name}
                        </h4>
                        {description && <div className="ExportedInsight-header-description">{description}</div>}
                    </div>

                    {showLogo && <FriendlyLogo style={{ fontSize: '1rem' }} />}
                </div>

                <div className="ExportedInsight-content">
                    <InsightViz insight={insight as any} style={{ top: 0, left: 0, position: 'relative' }} />
                    {showLegend ? (
                        <div className="pa">
                            <InsightLegend horizontal readOnly />
                        </div>
                    ) : null}
                </div>
            </div>
        </BindLogic>
    )
}
