import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement } from '@dnd-kit/modifiers'
import {
    SortableContext,
    arrayMove,
    horizontalListSortingStrategy,
    rectSortingStrategy,
    useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useMemo } from 'react'

import { IconDrag, IconGlobe, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'
import { LiveEventsFeed, LiveEventsFeedColumn } from 'scenes/activity/live/LiveEventsFeed'

import { WebAnalyticsDomainSelector } from '../WebAnalyticsFilters'
import { BreakdownLiveCard } from './BreakdownLiveCard'
import { getBrowserLogo } from './browserLogos'
import { LiveBotTrafficCard } from './LiveBotTrafficCard'
import { CONTENT_CARD_SPAN, LiveContentCardId, LiveStatCardId } from './liveCards'
import { LiveChartCard } from './LiveChartCard'
import { LiveStatCard, LiveStatDivider } from './LiveStatCard'
import { LiveTopPathsTable } from './LiveTopPathsTable'
import { LiveTopReferrersTable } from './LiveTopReferrersTable'
import { liveWebAnalyticsLayoutLogic } from './liveWebAnalyticsLayoutLogic'
import { BotEventsPerMinuteChart, UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'
import { BrowserBreakdownItem, CountryBreakdownItem, DeviceBreakdownItem } from './LiveWebAnalyticsMetricsTypes'
import { LiveWorldMap } from './LiveWorldMap'

const LIVE_FEED_COLUMNS: LiveEventsFeedColumn[] = ['event', 'person', 'url', 'timestamp']
const STATS_POLL_INTERVAL_MS = 1000

const renderBrowserIcon = (d: BrowserBreakdownItem): JSX.Element => {
    const Logo = getBrowserLogo(d.browser)
    return <Logo className="w-4 h-4 flex-shrink-0" />
}
const getBrowserKey = (d: BrowserBreakdownItem): string => d.browser
const getBrowserLabel = (d: BrowserBreakdownItem): string => d.browser
const getDeviceKey = (d: DeviceBreakdownItem): string => d.device
const getDeviceLabel = (d: DeviceBreakdownItem): string => d.device
const getCountryKey = (d: CountryBreakdownItem): string => d.country
const getCountryLabel = (d: CountryBreakdownItem): string => COUNTRY_CODE_TO_LONG_NAME[d.country] ?? d.country
const renderCountryIcon = (d: CountryBreakdownItem): JSX.Element => {
    if (d.country === 'Other') {
        return <IconGlobe className="w-4 h-4 flex-shrink-0 text-muted" />
    }
    return (
        <span
            className="w-4 h-4 inline-flex items-center justify-center text-base leading-none flex-shrink-0"
            aria-hidden
        >
            {countryCodeToFlag(d.country)}
        </span>
    )
}

const SortableCard = ({
    id,
    isEditing,
    className,
    children,
}: {
    id: string
    isEditing: boolean
    className?: string
    children: ReactNode
}): JSX.Element => {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id,
        disabled: !isEditing,
    })
    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
    }
    return (
        <div
            ref={setNodeRef}
            style={style}
            className={clsx(
                'relative',
                className,
                isEditing && 'rounded border-2 border-dashed border-primary p-1',
                isDragging && 'z-[999999] opacity-80'
            )}
            {...(isEditing ? attributes : {})}
        >
            {isEditing && (
                <button
                    type="button"
                    className="absolute top-1 right-1 z-10 cursor-move rounded bg-bg-light p-1 text-muted hover:text-default shadow-sm"
                    aria-label="Drag to reorder"
                    {...listeners}
                >
                    <IconDrag className="text-base" />
                </button>
            )}
            {children}
        </div>
    )
}

export const LiveWebAnalyticsMetrics = (): JSX.Element => {
    const {
        chartData,
        deviceBreakdown,
        browserBreakdown,
        countryBreakdown,
        topCountryBreakdown,
        topPaths,
        topReferrers,
        totalPageviews,
        totalUniqueVisitors,
        totalBrowsers,
        botBreakdown,
        totalBotEvents,
        liveUserCount,
        selectedHost,
        isLoading,
        recentEvents,
    } = useValues(liveWebAnalyticsMetricsLogic)
    const { pauseStream, resumeStream } = useActions(liveWebAnalyticsMetricsLogic)
    const { liveUserCount: allDomainsLiveUserCount } = useValues(
        liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS })
    )
    const { pauseStream: pauseLiveCount, resumeStream: resumeLiveCount } = useActions(
        liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS })
    )

    const { statOrder, cardOrder, isEditing: isEditingRaw } = useValues(liveWebAnalyticsLayoutLogic)
    const { setStatOrder, setCardOrder, setEditing, resetLayout } = useActions(liveWebAnalyticsLayoutLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const canEditLayout = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_EDIT_LAYOUT]
    const isEditing = canEditLayout && isEditingRaw
    const { isVisible } = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
            resumeLiveCount()
        } else {
            pauseStream()
            pauseLiveCount()
        }
    }, [isVisible, resumeStream, pauseStream, resumeLiveCount, pauseLiveCount])

    const timezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])
    const displayedLiveUserCount = selectedHost ? liveUserCount : allDomainsLiveUserCount

    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: { distance: 5 },
        })
    )

    const renderStatCard = (id: LiveStatCardId): JSX.Element => {
        switch (id) {
            case 'users_online':
                return (
                    <LiveStatCard
                        label="Users online"
                        value={displayedLiveUserCount}
                        isLoading={selectedHost ? isLoading : undefined}
                    />
                )
            case 'unique_visitors':
                return <LiveStatCard label="Unique visitors" value={totalUniqueVisitors} isLoading={isLoading} />
            case 'pageviews':
                return <LiveStatCard label="Pageviews" value={totalPageviews} isLoading={isLoading} />
        }
    }

    const renderContentCard = (id: LiveContentCardId): JSX.Element | null => {
        switch (id) {
            case 'active_users_chart':
                return (
                    <LiveChartCard
                        title="Active users per minute"
                        subtitle={timezone}
                        subtitleTooltip="Metrics are shown in your local timezone"
                        isLoading={isLoading}
                    >
                        <UsersPerMinuteChart data={chartData} />
                    </LiveChartCard>
                )
            case 'top_paths':
                return <LiveTopPathsTable paths={topPaths} isLoading={isLoading} totalPageviews={totalPageviews} />
            case 'top_referrers':
                return (
                    <LiveTopReferrersTable
                        referrers={topReferrers}
                        isLoading={isLoading}
                        totalPageviews={totalPageviews}
                    />
                )
            case 'devices':
                return (
                    <BreakdownLiveCard<DeviceBreakdownItem>
                        title="Devices"
                        data={deviceBreakdown}
                        getKey={getDeviceKey}
                        getLabel={getDeviceLabel}
                        emptyMessage="No device data"
                        statLabel="unique devices"
                        isLoading={isLoading}
                    />
                )
            case 'browsers':
                return (
                    <BreakdownLiveCard<BrowserBreakdownItem>
                        title="Browsers"
                        data={browserBreakdown}
                        getKey={getBrowserKey}
                        getLabel={getBrowserLabel}
                        renderIcon={renderBrowserIcon}
                        emptyMessage="No browser data"
                        statLabel="unique browsers"
                        totalCount={totalBrowsers}
                        isLoading={isLoading}
                    />
                )
            case 'top_countries':
                return (
                    <BreakdownLiveCard<CountryBreakdownItem>
                        title="Countries"
                        data={topCountryBreakdown}
                        getKey={getCountryKey}
                        getLabel={getCountryLabel}
                        renderIcon={renderCountryIcon}
                        emptyMessage="No country data"
                        statLabel="unique visitors"
                        isLoading={isLoading}
                    />
                )
            case 'bot_events_chart':
                if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]) {
                    return null
                }
                return (
                    <LiveChartCard
                        title="Bot requests per minute"
                        subtitle={timezone}
                        subtitleTooltip="Metrics are shown in your local timezone"
                        isLoading={isLoading}
                        contentClassName="h-64 md:h-80"
                    >
                        <BotEventsPerMinuteChart data={chartData} />
                    </LiveChartCard>
                )
            case 'bot_traffic':
                if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS]) {
                    return null
                }
                return (
                    <LiveBotTrafficCard
                        data={botBreakdown}
                        totalBotEvents={totalBotEvents}
                        totalEvents={totalPageviews}
                        isLoading={isLoading}
                    />
                )
            case 'countries':
                if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_MAP]) {
                    return null
                }
                return (
                    <LiveChartCard title="Countries" isLoading={isLoading} contentClassName="">
                        <LiveWorldMap
                            data={countryBreakdown}
                            totalEvents={countryBreakdown.reduce((sum, c) => sum + c.count, 0)}
                        />
                    </LiveChartCard>
                )
            case 'live_events':
                return (
                    <LiveChartCard title="Live events" isLoading={false} contentClassName="max-h-80 overflow-y-auto">
                        <LiveEventsFeed events={recentEvents} columns={LIVE_FEED_COLUMNS} />
                    </LiveChartCard>
                )
        }
    }

    const visibleStatEntries = statOrder.map((id) => ({ id, node: renderStatCard(id) }))

    const visibleContentEntries = cardOrder
        .map((id) => ({ id, node: renderContentCard(id) }))
        .filter((entry): entry is { id: LiveContentCardId; node: JSX.Element } => entry.node !== null)

    const reorder =
        <T extends string>(order: T[], setter: (next: T[]) => void) =>
        ({ active, over }: DragEndEvent): void => {
            if (!over || active.id === over.id) {
                return
            }
            const from = order.indexOf(active.id as T)
            const to = order.indexOf(over.id as T)
            if (from === -1 || to === -1) {
                return
            }
            setter(arrayMove(order, from, to))
        }

    return (
        <div className="LivePageviews mt-4">
            <LemonBanner
                type="info"
                className="mb-2"
                dismissKey="live-web-analytics-alpha-banner"
                action={{ children: 'Send feedback', id: 'live-web-analytics-feedback-button' }}
            >
                The Web Analytics live dashboard is in alpha. We'd love to hear what you think!
            </LemonBanner>

            {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_DOMAIN_FILTER] && (
                <div className="mb-4">
                    <WebAnalyticsDomainSelector />
                </div>
            )}

            {canEditLayout && (
                <div className="flex items-center justify-end gap-2 mb-2">
                    {isEditing ? (
                        <>
                            <LemonButton type="secondary" size="small" onClick={() => resetLayout()}>
                                Reset layout
                            </LemonButton>
                            <LemonButton type="primary" size="small" onClick={() => setEditing(false)}>
                                Done
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPencil />}
                            onClick={() => setEditing(true)}
                        >
                            Edit layout
                        </LemonButton>
                    )}
                </div>
            )}

            <DndContext
                sensors={sensors}
                modifiers={[restrictToParentElement]}
                onDragEnd={reorder(statOrder, setStatOrder)}
            >
                <SortableContext items={visibleStatEntries.map((e) => e.id)} strategy={horizontalListSortingStrategy}>
                    <div className="flex flex-wrap items-center gap-4 md:gap-6 mb-6">
                        {visibleStatEntries.map((entry, index) => (
                            <div key={entry.id} className="flex items-center gap-4 md:gap-6">
                                <SortableCard id={entry.id} isEditing={isEditing}>
                                    {entry.node}
                                </SortableCard>
                                {index < visibleStatEntries.length - 1 && <LiveStatDivider />}
                            </div>
                        ))}
                    </div>
                </SortableContext>
            </DndContext>

            <DndContext sensors={sensors} onDragEnd={reorder(cardOrder, setCardOrder)}>
                <SortableContext items={visibleContentEntries.map((e) => e.id)} strategy={rectSortingStrategy}>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                        {visibleContentEntries.map((entry) => (
                            <SortableCard
                                key={entry.id}
                                id={entry.id}
                                isEditing={isEditing}
                                className={clsx(CONTENT_CARD_SPAN[entry.id] === 'full' && 'md:col-span-2')}
                            >
                                {entry.node}
                            </SortableCard>
                        ))}
                    </div>
                </SortableContext>
            </DndContext>
        </div>
    )
}
