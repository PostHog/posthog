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
import { ReactNode, useEffect, useMemo, useState } from 'react'

import { IconDrag, IconFilter, IconGlobe, IconPencil, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, Popover } from '@posthog/lemon-ui'

import { FilterBar } from 'lib/components/FilterBar'
import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isWebAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/country'
import { LiveEventsFeed, LiveEventsFeedColumn } from 'scenes/activity/live/LiveEventsFeed'
import { teamLogic } from 'scenes/teamLogic'

import { PropertyOperator } from '~/types'

import { isLiveStreamFilter } from '../webAnalyticsFilterLogic'
import { WebAnalyticsDomainSelector, WebAnalyticsLiveDeviceToggle } from '../WebAnalyticsFilters'
import { webAnalyticsLogic } from '../webAnalyticsLogic'
import { BreakdownLiveCard } from './BreakdownLiveCard'
import { getBrowserLogo } from './browserLogos'
import { LiveBotTrafficCard } from './LiveBotTrafficCard'
import { CONTENT_CARD_SPAN, LiveContentCardId, LiveStatCardId } from './liveCards'
import { LiveChartCard } from './LiveChartCard'
import { LiveLocationsCard } from './LiveLocationsCard'
import { LivePersonDrillDown } from './LivePersonDrillDown'
import { LivePersonDrillDownSelection, livePersonDrillDownDrawerLogic } from './livePersonDrillDownDrawerLogic'
import { LiveStatCard, LiveStatDivider } from './LiveStatCard'
import { LiveTopPathsTable } from './LiveTopPathsTable'
import { LiveTopReferrersTable } from './LiveTopReferrersTable'
import { liveWebAnalyticsLayoutLogic } from './liveWebAnalyticsLayoutLogic'
import { BotEventsPerMinuteChart, UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'
import {
    BrowserBreakdownItem,
    buildCityKey,
    CityBreakdownItem,
    CountryBreakdownItem,
    DeviceBreakdownItem,
} from './LiveWebAnalyticsMetricsTypes'
import { LiveWorldMap } from './LiveWorldMap'

const LIVE_FEED_COLUMNS_WITH_RECORDINGS: LiveEventsFeedColumn[] = ['event', 'person', 'url', 'recording', 'timestamp']
const LIVE_FEED_COLUMNS_WITHOUT_RECORDINGS: LiveEventsFeedColumn[] = ['event', 'person', 'url', 'timestamp']
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

const LiveDashboardFilterRow = ({
    isEditing,
    resetLayout,
    setEditing,
}: {
    isEditing: boolean
    resetLayout: () => void
    setEditing: (isEditing: boolean) => void
}): JSX.Element => {
    const [displayFilters, setDisplayFilters] = useState(false)
    const { rawWebAnalyticsFilters, deviceTypeFilter, validatedDomainFilter } = useValues(webAnalyticsLogic)
    const { setCountryFilter, setReferrerFilter, setDeviceTypeFilter, setDomainFilter, setWebAnalyticsFilters } =
        useActions(webAnalyticsLogic)

    const hasDomainFilter = !!validatedDomainFilter && validatedDomainFilter !== 'all'
    const livePropertyFilters = rawWebAnalyticsFilters.filter(isLiveStreamFilter)
    const preservedOverviewFilters = rawWebAnalyticsFilters.filter((f) => !isLiveStreamFilter(f))
    const activeFilterCount = livePropertyFilters.length + (deviceTypeFilter ? 1 : 0)
    const hasFilters = activeFilterCount > 0 || hasDomainFilter

    const resetFilters = (): void => {
        setWebAnalyticsFilters(preservedOverviewFilters)
        setCountryFilter(null)
        setReferrerFilter(null)
        setDeviceTypeFilter(null)
        setDomainFilter(null)
    }

    const filtersContent = (
        <div className="w-96 max-w-[90vw] p-3">
            <div className="space-y-4">
                <div>
                    <div className="text-xs font-semibold text-muted uppercase mb-2">Property filters</div>
                    <PropertyFilters
                        disablePopover
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        operatorAllowlist={[PropertyOperator.Exact]}
                        onChange={(filters) => {
                            const nextLiveFilters = filters
                                .filter(isWebAnalyticsPropertyFilter)
                                .filter(isLiveStreamFilter)
                            setWebAnalyticsFilters([...preservedOverviewFilters, ...nextLiveFilters])
                        }}
                        propertyFilters={livePropertyFilters}
                        pageKey="web-analytics-live"
                        eventNames={['$pageview']}
                    />
                </div>

                <LemonDivider />

                <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-xs font-semibold text-muted">Device</span>
                    <WebAnalyticsLiveDeviceToggle fullWidth />
                </div>
                {hasFilters && (
                    <LemonButton size="small" type="tertiary" fullWidth icon={<IconX />} onClick={resetFilters}>
                        Clear filters
                    </LemonButton>
                )}
            </div>
        </div>
    )

    return (
        <FilterBar
            className="mb-4"
            left={null}
            right={
                <>
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
                    <Popover
                        visible={displayFilters}
                        onClickOutside={() => setDisplayFilters(false)}
                        placement="bottom-end"
                        overlay={filtersContent}
                    >
                        <LemonButton
                            icon={
                                <IconWithCount count={activeFilterCount} showZero={false}>
                                    <IconFilter />
                                </IconWithCount>
                            }
                            type="secondary"
                            size="small"
                            data-attr="web-analytics-live-filters"
                            onClick={() => setDisplayFilters(!displayFilters)}
                        >
                            Filters
                        </LemonButton>
                    </Popover>
                    <WebAnalyticsDomainSelector />
                </>
            }
        />
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
        topCityBreakdown,
        topPaths,
        topReferrers,
        totalPageviews,
        totalUniqueVisitors,
        totalBrowsers,
        botBreakdown,
        totalBotEvents,
        totalBotEligibleEvents,
        liveUserCount,
        hasActiveFilters,
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

    const { statOrder, cardOrder, isEditing } = useValues(liveWebAnalyticsLayoutLogic)
    const { setStatOrder, setCardOrder, setEditing, resetLayout } = useActions(liveWebAnalyticsLayoutLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const drillDownEnabled = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_PERSON_DRILLDOWN]
    const liveFeedColumns = currentTeam?.session_recording_opt_in
        ? LIVE_FEED_COLUMNS_WITH_RECORDINGS
        : LIVE_FEED_COLUMNS_WITHOUT_RECORDINGS
    const { openDrillDown } = useActions(livePersonDrillDownDrawerLogic)

    const buildRowClickHandler = <T,>(
        isClickable: (item: T) => boolean,
        toSelection: (item: T) => LivePersonDrillDownSelection
    ): ((item: T) => void) | undefined =>
        drillDownEnabled
            ? (item: T): void => {
                  if (isClickable(item)) {
                      openDrillDown(toSelection(item))
                  }
              }
            : undefined

    const countrySelection = (countryCode: string): LivePersonDrillDownSelection => ({
        breakdownType: 'country',
        breakdownValue: countryCode,
        breakdownLabel: COUNTRY_CODE_TO_LONG_NAME[countryCode] ?? countryCode,
    })

    const onCountryRowClick = buildRowClickHandler<CountryBreakdownItem>(
        (item) => item.country !== 'Other',
        (item) => countrySelection(item.country)
    )
    const onCityRowClick = buildRowClickHandler<CityBreakdownItem>(
        (item) => item.cityName !== 'Other',
        (item) => ({
            breakdownType: 'city',
            breakdownValue: buildCityKey(item.cityName, item.countryCode),
            breakdownLabel: item.countryCode ? `${item.cityName}, ${item.countryCode}` : item.cityName,
        })
    )
    const onDeviceRowClick = buildRowClickHandler<DeviceBreakdownItem>(
        (item) => item.device !== 'Other',
        (item) => ({ breakdownType: 'device', breakdownValue: item.device, breakdownLabel: item.device })
    )
    const onBrowserRowClick = buildRowClickHandler<BrowserBreakdownItem>(
        (item) => item.browser !== 'Other',
        (item) => ({ breakdownType: 'browser', breakdownValue: item.browser, breakdownLabel: item.browser })
    )
    const onMapCountryClick = drillDownEnabled
        ? (countryCode: string): void => openDrillDown(countrySelection(countryCode))
        : undefined
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
    const displayedLiveUserCount = hasActiveFilters ? liveUserCount : allDomainsLiveUserCount

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
                        isLoading={hasActiveFilters ? isLoading : undefined}
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
                        onItemClick={onDeviceRowClick}
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
                        onItemClick={onBrowserRowClick}
                    />
                )
            case 'top_countries':
                if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_CITY_BREAKDOWN]) {
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
                            onItemClick={onCountryRowClick}
                        />
                    )
                }
                return (
                    <LiveLocationsCard
                        countryData={topCountryBreakdown}
                        cityData={topCityBreakdown}
                        isLoading={isLoading}
                        onCountryClick={onCountryRowClick}
                        onCityClick={onCityRowClick}
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
                        totalEvents={totalBotEligibleEvents}
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
                            onCountryClick={onMapCountryClick}
                        />
                    </LiveChartCard>
                )
            case 'live_events':
                return (
                    <LiveChartCard title="Live events" isLoading={false} contentClassName="max-h-80 overflow-y-auto">
                        <LiveEventsFeed events={recentEvents} columns={liveFeedColumns} />
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
        <div className="LivePageviews">
            <LiveDashboardFilterRow isEditing={isEditing} resetLayout={resetLayout} setEditing={setEditing} />

            <LemonBanner
                type="info"
                className="mb-2"
                dismissKey="live-web-analytics-alpha-banner"
                action={{ children: 'Send feedback', id: 'live-web-analytics-feedback-button' }}
            >
                We'd love to hear what you think about the live dashboard.
            </LemonBanner>

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

            {drillDownEnabled && <LivePersonDrillDown />}
        </div>
    )
}
