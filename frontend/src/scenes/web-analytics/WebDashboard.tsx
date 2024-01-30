import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconUnfoldMore } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { WebAnalyticsHealthCheck } from 'scenes/web-analytics/WebAnalyticsHealthCheck'
import { QueryTile, TabsTile, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsModal } from 'scenes/web-analytics/WebAnalyticsModal'
import { WebAnalyticsNotice } from 'scenes/web-analytics/WebAnalyticsNotice'
import { WebQuery } from 'scenes/web-analytics/WebAnalyticsTile'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'
import { WebTabs } from 'scenes/web-analytics/WebTabs'

import { navigationLogic } from '~/layout/navigation/navigationLogic'

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
                <WebPropertyFilters
                    setWebAnalyticsFilters={setWebAnalyticsFilters}
                    webAnalyticsFilters={webAnalyticsFilters}
                />
                <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
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
                    return <QueryTileItem key={i} tile={tile} />
                } else if ('tabs' in tile) {
                    return <TabsTileItem key={i} tile={tile} />
                } else {
                    return null
                }
            })}
        </div>
    )
}

const QueryTileItem = ({ tile }: { tile: QueryTile }): JSX.Element => {
    const { query, title, layout, insightProps, tileId } = tile

    const { openModal } = useActions(webAnalyticsLogic)

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-6',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? 'xxl:order-12',
                layout.className
            )}
        >
            {title && <h2 className="m-0 mb-3">{title}</h2>}
            {tile.canOpenModal ? (
                <Link
                    onClick={() => {
                        openModal(tileId)
                    }}
                >
                    <IconUnfoldMore />
                </Link>
            ) : null}
            <WebQuery query={query} insightProps={insightProps} />
        </div>
    )
}

const TabsTileItem = ({ tile }: { tile: TabsTile }): JSX.Element => {
    const { layout } = tile

    const { openModal } = useActions(webAnalyticsLogic)

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
                canOpenModal: tab.canOpenModal,
            }))}
            tileId={tile.tileId}
            openModal={openModal}
        />
    )
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <>
            <WebAnalyticsModal />
            <WebAnalyticsNotice />
            <div className="WebAnalyticsDashboard w-full flex flex-col">
                <Filters />
                <WebAnalyticsHealthCheck />
                <Tiles />
            </div>
        </>
    )
}
