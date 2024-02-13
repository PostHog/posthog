import { IconExpand45 } from '@posthog/icons'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { isNotNil } from 'lib/utils'
import React from 'react'
import { WebAnalyticsHealthCheck } from 'scenes/web-analytics/WebAnalyticsHealthCheck'
import { QueryTile, TabsTile, TileId, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsModal } from 'scenes/web-analytics/WebAnalyticsModal'
import { WebAnalyticsNotice } from 'scenes/web-analytics/WebAnalyticsNotice'
import { WebQuery } from 'scenes/web-analytics/WebAnalyticsTile'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { QuerySchema } from '~/queries/schema'

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
                <div className="flex-1">
                    <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                </div>
                <ReloadAll />
            </div>
            <div className="bg-border h-px w-full mt-2" />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(webAnalyticsLogic)

    return (
        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 xxl:grid-cols-3 gap-x-4 gap-y-12">
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
    const { query, title, layout, insightProps, showPathCleaningControls, showIntervalSelect } = tile

    const { openModal } = useActions(webAnalyticsLogic)
    const { getNewInsightUrl } = useValues(webAnalyticsLogic)

    const buttonsRow = [
        tile.canOpenInsight ? (
            <LemonButton
                key="open-insight-button"
                to={getNewInsightUrl(tile.tileId)}
                icon={<IconOpenInNew />}
                size="small"
                type="secondary"
            >
                Open as new Insight
            </LemonButton>
        ) : null,
        tile.canOpenModal ? (
            <LemonButton
                key="open-modal-button"
                onClick={() => openModal(tile.tileId)}
                icon={<IconExpand45 />}
                size="small"
                type="secondary"
            >
                Show more
            </LemonButton>
        ) : null,
    ].filter(isNotNil)

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
            <WebQuery
                query={query}
                insightProps={insightProps}
                showPathCleaningControls={showPathCleaningControls}
                showIntervalSelect={showIntervalSelect}
            />
            {buttonsRow.length > 0 ? <div className="flex justify-end my-2 space-x-2">{buttonsRow}</div> : null}
        </div>
    )
}

const TabsTileItem = ({ tile }: { tile: TabsTile }): JSX.Element => {
    const { layout } = tile

    const { openModal } = useActions(webAnalyticsLogic)
    const { getNewInsightUrl } = useValues(webAnalyticsLogic)

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
                        showPathCleaningControls={tab.showPathCleaningControls}
                        insightProps={tab.insightProps}
                    />
                ),
                linkText: tab.linkText,
                title: tab.title,
                canOpenModal: !!tab.canOpenModal,
                canOpenInsight: !!tab.canOpenInsight,
                query: tab.query,
            }))}
            tileId={tile.tileId}
            openModal={openModal}
            getNewInsightUrl={getNewInsightUrl}
        />
    )
}

export const WebTabs = ({
    className,
    activeTabId,
    tabs,
    setActiveTabId,
    openModal,
    getNewInsightUrl,
    tileId,
}: {
    className?: string
    activeTabId: string
    tabs: {
        id: string
        title: string
        linkText: string
        content: React.ReactNode
        canOpenModal: boolean
        canOpenInsight: boolean
        query: QuerySchema
    }[]
    setActiveTabId: (id: string) => void
    openModal: (tileId: TileId, tabId: string) => void
    getNewInsightUrl: (tileId: TileId, tabId: string) => string
    tileId: TileId
}): JSX.Element => {
    const activeTab = tabs.find((t) => t.id === activeTabId)

    const buttonsRow = [
        activeTab?.canOpenInsight ? (
            <LemonButton
                key="open-insight-button"
                to={getNewInsightUrl(tileId, activeTabId)}
                icon={<IconOpenInNew />}
                size="small"
                type="secondary"
            >
                Open as new Insight
            </LemonButton>
        ) : null,
        activeTab?.canOpenModal ? (
            <LemonButton
                key="open-modal-button"
                onClick={() => openModal(tileId, activeTabId)}
                icon={<IconExpand45 />}
                size="small"
                type="secondary"
            >
                Show more
            </LemonButton>
        ) : null,
    ].filter(isNotNil)

    return (
        <div className={clsx(className, 'flex flex-col')}>
            <div className="flex flex-row items-center self-stretch mb-3">
                <h2 className="flex-1 m-0">{activeTab?.title}</h2>

                {tabs.length > 3 ? (
                    <LemonSelect
                        size="small"
                        disabled={false}
                        value={activeTabId}
                        dropdownMatchSelectWidth={false}
                        onChange={setActiveTabId}
                        options={tabs.map(({ id, linkText }) => ({ value: id, label: linkText }))}
                    />
                ) : (
                    <LemonSegmentedButton
                        size="small"
                        options={tabs.map(({ id, linkText }) => ({ label: linkText, value: id }))}
                        onChange={(value) => setActiveTabId(value)}
                        value={activeTabId}
                    />
                )}
            </div>
            <div className="flex-1 flex flex-col">{activeTab?.content}</div>
            {buttonsRow.length > 0 ? <div className="flex justify-end my-2 space-x-2">{buttonsRow}</div> : null}
        </div>
    )
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <BindLogic logic={webAnalyticsLogic} props={{}}>
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: 'web-analytics' }}>
                <WebAnalyticsModal />
                <WebAnalyticsNotice />
                <div className="WebAnalyticsDashboard w-full flex flex-col">
                    <Filters />
                    <WebAnalyticsHealthCheck />
                    <Tiles />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
