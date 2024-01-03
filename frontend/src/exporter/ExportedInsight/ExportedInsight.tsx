import './ExportedInsight.scss'

import clsx from 'clsx'
import { BindLogic } from 'kea'
import { FilterBasedCardContent } from 'lib/components/Cards/InsightCard/InsightCard'
import { QueriesUnsupportedHere } from 'lib/components/Cards/InsightCard/QueriesUnsupportedHere'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

import { ExportOptions, ExportType } from '~/exporter/types'
import { Query } from '~/queries/Query/Query'
import { isDataTableNode } from '~/queries/utils'
import { Logo } from '~/toolbar/assets/Logo'
import { ChartDisplayType, InsightLogicProps, InsightModel } from '~/types'

export function ExportedInsight({
    insight,
    exportOptions: { whitelabel, noHeader, legend },
    type,
}: {
    insight: InsightModel
    exportOptions: ExportOptions
    type: ExportType
}): JSX.Element {
    if (isTrendsFilter(insight.filters) && insight.filters.show_legend) {
        // legend is always shown so don't show it alongside the insight
        insight.filters.show_legend = false
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

    const { filters, query, name, derived_name, description } = insight

    const showLegend =
        legend &&
        isTrendsFilter(filters) &&
        (!filters.display ||
            (!SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display) &&
                filters.display !== ChartDisplayType.ActionsTable))
    const showWatermark = noHeader && !whitelabel

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
                    {query ? (
                        insight.result ? (
                            <Query query={query} cachedResults={insight.result} readOnly />
                        ) : (
                            <QueriesUnsupportedHere />
                        )
                    ) : (
                        <FilterBasedCardContent insight={insight as any} insightProps={insightLogicProps} />
                    )}
                    {showLegend ? (
                        <div className="p-4">
                            <InsightLegend horizontal readOnly />
                        </div>
                    ) : null}
                </div>
            </div>
        </BindLogic>
    )
}
