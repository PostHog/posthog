import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPropertyOrPersonPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { WebAnalyticsHealthCheck } from 'scenes/web-analytics/WebAnalyticsHealthCheck'
import { TabsTile, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsNotice } from 'scenes/web-analytics/WebAnalyticsNotice'
import {
    webAnalyticsDataTableQueryContext,
    WebStatsTableTile,
    WebStatsTrendTile,
} from 'scenes/web-analytics/WebAnalyticsTile'
import { WebTabs } from 'scenes/web-analytics/WebTabs'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

const Filters = (): JSX.Element => {
    const {
        webAnalyticsFilters,
        dateFilter: { dateTo, dateFrom },
    } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters, setDates } = useActions(webAnalyticsLogic)
    const { mobileLayout } = useValues(navigationLogic)

    return (
        <div
            className="sticky z-20 pt-2"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: 'var(--bg-3000)',
                top: mobileLayout ? 'var(--breadcrumbs-height-full)' : 'var(--breadcrumbs-height-compact)',
            }}
        >
            <div className="flex flex-row flex-wrap gap-2">
                <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                <PropertyFilters
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                    onChange={(filters) =>
                        setWebAnalyticsFilters(filters.filter(isEventPropertyOrPersonPropertyFilter))
                    }
                    propertyFilters={webAnalyticsFilters}
                    pageKey="web-analytics"
                    eventNames={['$pageview', '$pageleave', '$autocapture']}
                    propertyAllowList={{
                        [TaxonomicFilterGroupType.EventProperties]: [
                            '$pathname',
                            '$host',
                            '$browser',
                            '$os',
                            '$device_type',
                            '$geoip_country_code',
                            '$geoip_subdivision_1_code',
                            '$geoip_city_name',
                            // re-enable after https://github.com/PostHog/posthog-js/pull/875 is merged
                            // '$client_session_initial_pathname',
                            // '$client_session_initial_referring_host',
                            // '$client_session_initial_utm_source',
                            // '$client_session_initial_utm_campaign',
                            // '$client_session_initial_utm_medium',
                            // '$client_session_initial_utm_content',
                            // '$client_session_initial_utm_term',
                        ],
                        [TaxonomicFilterGroupType.PersonProperties]: [
                            '$initial_pathname',
                            '$initial_referring_domain',
                            '$initial_utm_source',
                            '$initial_utm_campaign',
                            '$initial_utm_medium',
                            '$initial_utm_content',
                            '$initial_utm_term',
                        ],
                    }}
                />
            </div>
            <div className="bg-border h-px w-full mt-2" />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(webAnalyticsLogic)

    return (
        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 xxl:grid-cols-3 gap-x-4 gap-y-10">
            {tiles.map((tile, i) => {
                if ('query' in tile) {
                    const { query, title, layout, insightProps } = tile
                    return (
                        <div
                            key={i}
                            className={clsx(
                                'col-span-1 row-span-1 flex flex-col',
                                layout.colSpanClassName ?? 'md:col-span-6',
                                layout.rowSpanClassName ?? 'md:row-span-1',
                                layout.orderWhenLargeClassName ?? 'xxl:order-12',
                                layout.className
                            )}
                        >
                            {title && <h2 className="m-0 mb-3">{title}</h2>}
                            <WebQuery query={query} insightProps={insightProps} />
                        </div>
                    )
                } else if ('tabs' in tile) {
                    return <TabsTileItem key={i} tile={tile} />
                } else {
                    return null
                }
            })}
        </div>
    )
}

const TabsTileItem = ({ tile }: { tile: TabsTile }): JSX.Element => {
    const { layout } = tile

    return (
        <WebTabs
            className={clsx(
                'col-span-1 row-span-1',
                layout.colSpanClassName || 'md:col-span-1',
                layout.rowSpanClassName || 'md:row-span-1',
                layout.orderWhenLargeClassName || 'xxl:order-12',
                layout.className
            )}
            activeTabId={tile.activeTabId}
            setActiveTabId={tile.setTabId}
            tabs={tile.tabs.map((tab) => ({
                id: tab.id,
                content: (
                    <WebQuery
                        key={tab.id}
                        query={tab.query}
                        showIntervalSelect={tab.showIntervalSelect}
                        insightProps={tab.insightProps}
                    />
                ),
                linkText: tab.linkText,
                title: tab.title,
            }))}
        />
    )
}

const WebQuery = ({
    query,
    showIntervalSelect,
    insightProps,
}: {
    query: QuerySchema
    showIntervalSelect?: boolean
    insightProps: InsightLogicProps
}): JSX.Element => {
    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebStatsTableQuery) {
        return <WebStatsTableTile query={query} breakdownBy={query.source.breakdownBy} insightProps={insightProps} />
    }
    if (query.kind === NodeKind.InsightVizNode) {
        return <WebStatsTrendTile query={query} showIntervalTile={showIntervalSelect} insightProps={insightProps} />
    }

    return <Query query={query} readOnly={true} context={{ ...webAnalyticsDataTableQueryContext, insightProps }} />
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <>
            <WebAnalyticsNotice />
            <div className="WebAnalyticsDashboard w-full flex flex-col">
                <Filters />
                <WebAnalyticsHealthCheck />
                <Tiles />
            </div>
        </>
    )
}
