import './ExportedInsight.scss'

import clsx from 'clsx'
import { BindLogic, useMountedLogic } from 'kea'

import { Logo } from 'lib/brand'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import {
    DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS,
    DISPLAY_TYPES_WITHOUT_LEGEND,
} from 'lib/components/InsightLegend/utils'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { DISPLAYS_WITH_IN_CHART_LEGEND } from 'scenes/insights/insightVizDataLogic'
import { BoxPlotLegend } from 'scenes/insights/views/BoxPlot/BoxPlotLegend'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { isDataTableNode, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, DataColorThemeModel, InsightLogicProps, InsightModel } from '~/types'

export function ExportedInsight({
    insight: legacyInsight,
    themes,
    exportOptions: { whitelabel, noHeader, legend, detailed: detailedResults },
}: {
    insight: InsightModel
    themes: DataColorThemeModel[]
    exportOptions: SharingConfigurationSettings
}): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    const insight = getQueryBasedInsightModel(legacyInsight)
    // getQueryBasedInsightModel returns the caller's query object by reference — clone it so the
    // export-only tweaks below (legend settings, table editing controls) can't leak into a shared model.
    insight.query = insight.query ? structuredClone(insight.query) : insight.query

    if (isDataTableNode(insight.query)) {
        // don't show editing controls when exporting/sharing
        insight.query.full = false
        insight.query.showHogQLEditor = false
        insight.query.showActions = false
    }

    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        cachedInsight: insight,
        doNotLoad: true,
    }

    const { short_id, query, name, derived_name, description } = insight

    const showWatermark = noHeader && !whitelabel
    const trendsDisplay =
        isInsightVizNode(query) && isTrendsQuery(query.source) ? query.source.trendsFilter?.display : undefined
    const isBoxPlot = trendsDisplay === ChartDisplayType.BoxPlot
    const isMetric = trendsDisplay === ChartDisplayType.Metric
    const showLegend =
        legend &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        !SINGLE_SERIES_DISPLAY_TYPES.includes(trendsDisplay as ChartDisplayType) &&
        !DISPLAY_TYPES_WITHOUT_LEGEND.includes(trendsDisplay as ChartDisplayType)

    // Displays covered by the quill in-chart legend draw the legend inside the chart itself.
    const usesQuillInChartLegend =
        !trendsDisplay || DISPLAYS_WITH_IN_CHART_LEGEND.includes(trendsDisplay as ChartDisplayType)

    if (isInsightVizNode(insight.query) && isTrendsQuery(insight.query.source)) {
        if (usesQuillInChartLegend) {
            // The export `legend` option decides whether the chart shows its in-chart quill legend,
            // pinned to the bottom to match the legacy exported layout (legend below the chart).
            insight.query.source.trendsFilter = {
                ...insight.query.source.trendsFilter,
                showLegend: !!showLegend,
                legendPosition: 'bottom',
            }
        } else if (insight.query.source.trendsFilter?.showLegend) {
            // legend is rendered separately below so don't show it alongside the insight too
            insight.query.source.trendsFilter.showLegend = false
        }
    }

    const showDetailedResultsTable =
        detailedResults &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        !DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS.includes(query.source.trendsFilter?.display as ChartDisplayType)

    return (
        <BindLogic logic={insightLogic} props={insightLogicProps}>
            <div className={clsx('ExportedInsight', isMetric && 'ExportedInsight--metric')}>
                {!noHeader && (
                    <div className="ExportedInsight__header">
                        <div>
                            <h5>
                                <TopHeading query={query} />
                            </h5>
                            <h4 title={name} className="ExportedInsight__header__title">
                                {name || derived_name}
                            </h4>
                            {description && <div className="ExportedInsight__header-description">{description}</div>}
                        </div>

                        {!whitelabel && <Logo size="xs" className="shrink-0 ml-3" />}
                    </div>
                )}
                {showWatermark && (
                    <div className="ExportedInsight__watermark">
                        <Logo size="xs" />
                    </div>
                )}
                <div
                    className={clsx({
                        ExportedInsight__content: true,
                        'ExportedInsight__content--with-watermark': showWatermark,
                    })}
                >
                    <Query
                        query={insight.query}
                        cachedResults={insight}
                        readOnly
                        context={{ insightProps: insightLogicProps }}
                        embedded
                        inSharedMode
                    />
                    {showLegend && !usesQuillInChartLegend && (
                        <div className="p-4">
                            {isBoxPlot ? <BoxPlotLegend horizontal /> : <InsightLegend horizontal readOnly />}
                        </div>
                    )}
                    {showDetailedResultsTable && (
                        <div className="border-t mt-2">
                            <InsightsTable filterKey={short_id} isLegend embedded editMode={false} />
                        </div>
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
