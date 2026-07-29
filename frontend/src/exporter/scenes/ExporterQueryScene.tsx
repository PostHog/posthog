import '../ExportedInsight/ExportedInsight.scss'

import clsx from 'clsx'
import { BindLogic, useMountedLogic } from 'kea'
import { useMemo } from 'react'

import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { DISPLAY_TYPES_WITHOUT_LEGEND } from 'lib/components/InsightLegend/utils'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { DISPLAYS_WITH_IN_CHART_LEGEND } from 'scenes/insights/insightVizDataLogic'

import { Query } from '~/queries/Query/Query'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { getDisplay, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { ExportedData } from '../types'

/**
 * Renders an ad-hoc query export (`export_context.source`, no saved insight) from the
 * pre-computed result the sharing view inlined — never POSTs to the query API, which the
 * asset token can't authenticate. Reuses the ExportedInsight classes so the image
 * exporter's wait selector and content measurement work unchanged.
 */
export default function ExporterQueryScene({
    query,
    queryResults,
    themes,
    exportOptions,
}: {
    query: NonNullable<ExportedData['query']>
    queryResults: ExportedData['query_results']
    themes: NonNullable<ExportedData['themes']>
    exportOptions: SharingConfigurationSettings
}): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    // getDisplay rather than a raw trendsFilter read, so deprecated display aliases pick the same
    // legend layout here as the chart they get normalized to.
    const trendsDisplay = isInsightVizNode(query) && isTrendsQuery(query.source) ? getDisplay(query.source) : undefined
    const showLegend =
        exportOptions.legend &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        !SINGLE_SERIES_DISPLAY_TYPES.includes(trendsDisplay as ChartDisplayType) &&
        !DISPLAY_TYPES_WITHOUT_LEGEND.includes(trendsDisplay as ChartDisplayType)

    // Displays covered by the quill in-chart legend draw the legend inside the chart itself.
    const usesQuillInChartLegend =
        !trendsDisplay || DISPLAYS_WITH_IN_CHART_LEGEND.includes(trendsDisplay as ChartDisplayType)

    // Memoized because insightDataLogic re-syncs its query from `props.query` whenever the props it was
    // built with change. A fresh object every render would revert local view state — such as a series
    // the viewer hid from the legend — on the next render.
    const exportedQuery = useMemo<NonNullable<ExportedData['query']>>(() => {
        if (!isInsightVizNode(query) || !isTrendsQuery(query.source)) {
            return query
        }
        return {
            ...query,
            source: {
                ...query.source,
                trendsFilter: usesQuillInChartLegend
                    ? // Pinned to the bottom to match the legacy exported layout (legend below the chart).
                      { ...query.source.trendsFilter, showLegend: !!showLegend, legendPosition: 'bottom' }
                    : // The legend is rendered separately below, so don't show it alongside the chart too.
                      { ...query.source.trendsFilter, showLegend: false },
            },
        }
    }, [query, showLegend, usesQuillInChartLegend])

    // `query` carries the display type, breakdown, and formulas. Without it insightDataLogic falls back
    // to a bare default TrendsQuery, and every ad-hoc export renders as a plain line chart. The
    // `new-AdHoc.` prefix is what gates that props-query path — insightDataLogic ignores `props.query`
    // under any other dashboardItemId.
    const insightLogicProps: InsightLogicProps = useMemo(
        () => ({
            dashboardItemId: 'new-AdHoc.export',
            query: exportedQuery,
            doNotLoad: true,
        }),
        [exportedQuery]
    )

    return (
        <BindLogic logic={insightLogic} props={insightLogicProps}>
            <div
                className={clsx(
                    'ExportedInsight',
                    trendsDisplay === ChartDisplayType.Metric && 'ExportedInsight--metric'
                )}
            >
                <div className="ExportedInsight__content">
                    <Query
                        query={exportedQuery}
                        cachedResults={queryResults}
                        context={{ insightProps: insightLogicProps }}
                        embedded
                        readOnly
                        inSharedMode
                    />
                    {showLegend && !usesQuillInChartLegend && (
                        <div className="p-4">
                            <InsightLegend horizontal readOnly />
                        </div>
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
