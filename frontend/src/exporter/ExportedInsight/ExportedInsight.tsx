import './ExportedInsight.scss'

import clsx from 'clsx'
import { BindLogic } from 'kea'
import { FilterBasedCardContent } from 'lib/components/Cards/InsightCard/InsightCard'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ExportOptions, ExportType } from '~/exporter/types'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { isDataTableNode, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { Logo } from '~/toolbar/assets/Logo'
import { ChartDisplayType, InsightLogicProps, InsightModel } from '~/types'

export function ExportedInsight({
    insight: legacyInsight,
    exportOptions: { whitelabel, noHeader, legend },
    type,
}: {
    insight: InsightModel
    exportOptions: ExportOptions
    type: ExportType
}): JSX.Element {
    const insight = getQueryBasedInsightModel(legacyInsight)

    if (
        isInsightVizNode(insight.query) &&
        isTrendsQuery(insight.query.source) &&
        insight.query.source.trendsFilter &&
        insight.query.source.trendsFilter.showLegend == true
    ) {
        // legend is always shown so don't show it alongside the insight
        insight.query.source.trendsFilter.showLegend = false
    }

    if (isDataTableNode(insight.query)) {
        // don't show editing controls when exporting/sharing
        insight.query.full = false
        insight.query.showHogQLEditor = false
        insight.query.showActions = false
    }

    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        cachedInsight: legacyInsight, // TODO: use query based insight here
        doNotLoad: true,
    }

    const { query, name, derived_name, description } = insight

    const showWatermark = noHeader && !whitelabel
    const showLegend =
        legend &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        (!query.source.trendsFilter ||
            !query.source.trendsFilter.display ||
            (!SINGLE_SERIES_DISPLAY_TYPES.includes(query.source.trendsFilter.display) &&
                query.source.trendsFilter.display !== ChartDisplayType.ActionsTable))

    return (
        <BindLogic logic={insightLogic} props={insightLogicProps}>
            <div
                className={clsx('ExportedInsight', {
                    'ExportedInsight--fit-screen': type === ExportType.Embed,
                })}
            >
                {!noHeader && (
                    <div className="ExportedInsight__header">
                        <div>
                            <h5>
                                <TopHeading insight={insight} />
                            </h5>
                            <h4 title={name} className="ExportedInsight__header__title">
                                {name || derived_name}
                            </h4>
                            {description && <div className="ExportedInsight__header-description">{description}</div>}
                        </div>

                        {!whitelabel && <Logo />}
                    </div>
                )}
                {showWatermark && (
                    <div className="ExportedInsight__watermark">
                        <Logo />
                    </div>
                )}
                <div
                    className={clsx({
                        ExportedInsight__content: true,
                        'ExportedInsight__content--with-watermark': showWatermark,
                    })}
                >
                    {legacyInsight.query ? (
                        <Query query={legacyInsight.query} cachedResults={legacyInsight} readOnly />
                    ) : (
                        <FilterBasedCardContent insight={legacyInsight} insightProps={insightLogicProps} />
                    )}
                    {showLegend && (
                        <div className="p-4">
                            <InsightLegend horizontal readOnly />
                        </div>
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
