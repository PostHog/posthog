import './ExportedInsight.scss'

import clsx from 'clsx'
import { BindLogic, useMountedLogic } from 'kea'

import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import {
    DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS,
    DISPLAY_TYPES_WITHOUT_LEGEND,
} from 'lib/components/InsightLegend/utils'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'

import { Query } from '~/queries/Query/Query'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { isDataTableNode, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { Logo } from '~/toolbar/assets/Logo'
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
        cachedInsight: insight,
        doNotLoad: true,
    }

    const { short_id, query, name, derived_name, description } = insight

    const showWatermark = noHeader && !whitelabel
    const showLegend =
        legend &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        !SINGLE_SERIES_DISPLAY_TYPES.includes(query.source.trendsFilter?.display as ChartDisplayType) &&
        !DISPLAY_TYPES_WITHOUT_LEGEND.includes(query.source.trendsFilter?.display as ChartDisplayType)

    const showDetailedResultsTable =
        detailedResults &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        !DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS.includes(query.source.trendsFilter?.display as ChartDisplayType)

    return (
        <BindLogic logic={insightLogic} props={insightLogicProps}>
            <div className="ExportedInsight">
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
                    <Query
                        query={insight.query}
                        cachedResults={insight}
                        readOnly
                        context={{ insightProps: insightLogicProps }}
                        embedded
                        inSharedMode
                    />
                    {showLegend && (
                        <div className="p-4">
                            <InsightLegend horizontal readOnly />
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
