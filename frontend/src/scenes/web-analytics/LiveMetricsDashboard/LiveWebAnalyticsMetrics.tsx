import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconGlobe } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'
import { LiveEventsFeed, LiveEventsFeedColumn } from 'scenes/activity/live/LiveEventsFeed'

import { BreakdownLiveCard } from './BreakdownLiveCard'
import { getBrowserLogo } from './browserLogos'
import { LiveChartCard } from './LiveChartCard'
import { LiveStatCard, LiveStatDivider } from './LiveStatCard'
import { LiveTopPathsTable } from './LiveTopPathsTable'
import { LiveTopReferrersTable } from './LiveTopReferrersTable'
import { UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
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
        isLoading,
        recentEvents,
    } = useValues(liveWebAnalyticsMetricsLogic)
    const { pauseStream, resumeStream } = useActions(liveWebAnalyticsMetricsLogic)
    const { liveUserCount } = useValues(liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS }))
    const { pauseStream: pauseLiveCount, resumeStream: resumeLiveCount } = useActions(
        liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS })
    )

    const { featureFlags } = useValues(featureFlagLogic)
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
            <div className="flex flex-wrap items-center gap-4 md:gap-6 mb-6">
                <LiveStatCard label="Users online" value={liveUserCount} />
                <LiveStatDivider />
                <LiveStatCard label="Unique visitors" value={totalUniqueVisitors} isLoading={isLoading} />
                <LiveStatDivider />
                <LiveStatCard label="Pageviews" value={totalPageviews} isLoading={isLoading} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <LiveChartCard
                    title="Active users per minute"
                    subtitle={timezone}
                    subtitleTooltip="Metrics are shown in your local timezone"
                    isLoading={isLoading}
                    contentClassName="h-64 md:h-80"
                >
                    <UsersPerMinuteChart data={chartData} />
                </LiveChartCard>

                <LiveTopPathsTable paths={topPaths} isLoading={isLoading} totalPageviews={totalPageviews} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <LiveTopReferrersTable referrers={topReferrers} isLoading={isLoading} totalPageviews={totalPageviews} />
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
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <BreakdownLiveCard<DeviceBreakdownItem>
                    title="Devices"
                    data={deviceBreakdown}
                    getKey={getDeviceKey}
                    getLabel={getDeviceLabel}
                    emptyMessage="No device data"
                    statLabel="unique devices"
                    isLoading={isLoading}
                />
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
            </div>

            {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_MAP] && (
                <LiveChartCard title="Countries" isLoading={isLoading} contentClassName="">
                    <LiveWorldMap
                        data={countryBreakdown}
                        totalEvents={countryBreakdown.reduce((sum, c) => sum + c.count, 0)}
                    />
                </LiveChartCard>
            )}

            <div className="mb-6">
                <LiveChartCard title="Live events" isLoading={false} contentClassName="max-h-80 overflow-y-auto">
                    <LiveEventsFeed events={recentEvents} columns={LIVE_FEED_COLUMNS} />
                </LiveChartCard>
            </div>
        </div>
    )
}
