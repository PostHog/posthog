import '../ExportedInsight/ExportedInsight.scss'

import { BindLogic, useMountedLogic } from 'kea'

import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { DISPLAY_TYPES_WITHOUT_LEGEND } from 'lib/components/InsightLegend/utils'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
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

    if (isInsightVizNode(query) && isTrendsQuery(query.source) && query.source.trendsFilter?.showLegend) {
        // The exporter renders its own horizontal legend below the chart, never the
        // in-chart side legend — mirrors ExportedInsight.
        query = {
            ...query,
            source: { ...query.source, trendsFilter: { ...query.source.trendsFilter, showLegend: false } },
        }
    }

    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: 'new-adhoc-export',
        doNotLoad: true,
    }

    const trendsDisplay =
        isInsightVizNode(query) && isTrendsQuery(query.source) ? query.source.trendsFilter?.display : undefined
    const showLegend =
        exportOptions.legend &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        !SINGLE_SERIES_DISPLAY_TYPES.includes(trendsDisplay as ChartDisplayType) &&
        !DISPLAY_TYPES_WITHOUT_LEGEND.includes(trendsDisplay as ChartDisplayType)

    return (
        <BindLogic logic={insightLogic} props={insightLogicProps}>
            <div className="ExportedInsight">
                <div className="ExportedInsight__content">
                    <Query
                        query={query}
                        cachedResults={queryResults}
                        context={{ insightProps: insightLogicProps }}
                        embedded
                        readOnly
                        inSharedMode
                    />
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
