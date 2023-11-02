import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { TabsTile, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { WebAnalyticsNotice } from 'scenes/web-analytics/WebAnalyticsNotice'
import { webAnalyticsDataTableQueryContext, WebStatsTableTile } from 'scenes/web-analytics/WebAnalyticsDataTable'
import { WebTabs } from 'scenes/web-analytics/WebTabs'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

const Filters = (): JSX.Element => {
    const { webAnalyticsFilters, dateTo, dateFrom } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters, setDates } = useActions(webAnalyticsLogic)
    return (
        <div className="sticky top-0 bg-white z-20 pt-2">
            <div className="flex flex-row flex-wrap gap-2">
                <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                <PropertyFilters
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPropertyFilter))}
                    propertyFilters={webAnalyticsFilters}
                    pageKey={'web-analytics'}
                    eventNames={['$pageview', '$pageleave', '$autocapture']}
                />
            </div>
            <div className={'bg-border h-px w-full mt-2'} />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(webAnalyticsLogic)

    return (
        <div className="mt-2 grid grid-cols-1 md:grid-cols-12 gap-4">
            {tiles.map((tile, i) => {
                if ('query' in tile) {
                    const { query, title, layout } = tile
                    return (
                        <div
                            key={i}
                            className={`col-span-1 row-span-1 md:col-span-${layout.colSpan ?? 6} md:row-span-${
                                layout.rowSpan ?? 1
                            }  flex flex-col`}
                        >
                            {title && <h2 className="m-0  mb-1">{title}</h2>}
                            <WebQuery query={query} />
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
            className={`col-span-1 row-span-1 md:col-span-${layout.colSpan ?? 6} md:row-span-${layout.rowSpan ?? 1}`}
            activeTabId={tile.activeTabId}
            setActiveTabId={tile.setTabId}
            tabs={tile.tabs.map((tab) => ({
                id: tab.id,
                content: <WebQuery key={tab.id} query={tab.query} />,
                linkText: tab.linkText,
                title: tab.title,
            }))}
        />
    )
}

const WebQuery = ({ query }: { query: QuerySchema }): JSX.Element => {
    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebStatsTableQuery) {
        return <WebStatsTableTile query={query} breakdownBy={query.source.breakdownBy} />
    }

    return <Query query={query} readOnly={true} context={webAnalyticsDataTableQueryContext} />
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <div className="w-full flex flex-col pt-2">
            <WebAnalyticsNotice />
            <Filters />
            <Tiles />
        </div>
    )
}
