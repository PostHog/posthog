import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import uniqueVisitorsMock from './__mocks__/UniqueVisitors.json'
import webOverviewMock from './__mocks__/WebOverview.json'
import { DeviceTab, SourceTab } from './common'
import browserMock from './tiles/__mocks__/Browser.json'
import pathMock from './tiles/__mocks__/Path.json'
import referringDomainMock from './tiles/__mocks__/ReferringDomain.json'
import retentionMock from './tiles/__mocks__/Retention.json'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const ALL_VIEWPORT_WIDTHS = ['narrow', 'medium', 'wide', 'superwide'] as const

// Valid-but-empty query response. Tabs whose specific query kinds we don't richly mock
// (web vitals, bot analytics, live metrics) still render their layout chrome instead of
// hanging on a loader or erroring — which is all we need to catch responsive regressions.
const EMPTY_QUERY_RESPONSE = {
    results: [],
    columns: [],
    types: [],
    hogql: '',
    error: null,
    hasMore: false,
    limit: 100,
    offset: 0,
}

const webAnalyticsMswDecorator = mswDecorator({
    get: {
        // Live count of users on product
        '/stats': () => [200, { users_on_product: 2387 }],

        // Avoid displaying error of missing $pageview/$pageleave/$web_vitals events
        '/api/projects/:team_id/event_definitions': () => [200, { count: 5 }],
        '/api/environments/:team_id/event_definitions': () => [200, { count: 5, results: [] }],
        '/api/environments/:team_id/property_definitions': () => [200, { count: 0, results: [] }],

        // Health tab checks
        '/api/environments/:team_id/authorized_urls': () => [200, { count: 0, results: [] }],
        '/api/environments/:team_id/hog_functions': () => [200, { count: 0, results: [] }],

        // Marketing / warehouse integrations referenced by some tabs
        '/api/environments/:team_id/external_data_sources': () => [200, { count: 0, results: [] }],
    },
    post: {
        '/api/environments/:team_id/query/:kind': (req) => {
            const query = (req.body as any).query
            const queryKind = query.kind

            if (queryKind === 'DatabaseSchemaQuery') {
                return [200, { tables: {}, joins: [] }] // Empty schema, we don't care about this here
            } else if (queryKind === 'WebOverviewQuery') {
                return [200, webOverviewMock]
            } else if (queryKind === 'TrendsQuery') {
                return [200, uniqueVisitorsMock]
            } else if (queryKind === 'WebStatsTableQuery') {
                if (query.breakdownBy === 'Page') {
                    return [200, pathMock]
                } else if (query.breakdownBy === 'InitialReferringDomain') {
                    return [200, referringDomainMock]
                } else if (query.breakdownBy === 'Browser') {
                    return [200, browserMock]
                }
                return [200, EMPTY_QUERY_RESPONSE]
            } else if (queryKind === 'RetentionQuery') {
                return [200, retentionMock]
            }

            // Web vitals, bot analytics (HogQL), live metrics, etc. — render empty rather than hang.
            return [200, EMPTY_QUERY_RESPONSE]
        },
    },
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Web Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.webAnalytics(),
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2],
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [webAnalyticsMswDecorator],
}
export default meta

export function WebAnalyticsDashboard(): JSX.Element {
    const { setSourceTab, setDeviceTab } = useActions(webAnalyticsLogic)

    useEffect(() => {
        // Set the source tab to referring domain
        setSourceTab(SourceTab.REFERRING_DOMAIN)

        // Set the device tab to browsers
        setDeviceTab(DeviceTab.BROWSER)
    }, [setDeviceTab, setSourceTab])

    return <App />
}
WebAnalyticsDashboard.parameters = {
    testOptions: {
        includeNavigationInSnapshot: true,
        waitForLoadersToDisappear: true,
        waitForSelector: '[data-attr=trend-line-graph] > canvas',
    },
}

// Snapshot every web analytics tab across viewport widths so narrow-screen layout regressions are
// caught. `narrow` (568px) is the one that surfaces the responsive issues; the wider presets guard
// against the opposite — a narrow fix shouldn't break the roomier layouts. Each tab is reached via
// its URL (`pageUrl`), which drives `productTab` through the scene's router.

WebAnalyticsDashboardViewports.parameters = {
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2],
    testOptions: {
        includeNavigationInSnapshot: true,
        waitForLoadersToDisappear: true,
        waitForSelector: '[data-attr=trend-line-graph] > canvas',
        viewportWidths: ALL_VIEWPORT_WIDTHS,
    },
}
export function WebAnalyticsDashboardViewports(): JSX.Element {
    const { setSourceTab, setDeviceTab } = useActions(webAnalyticsLogic)

    useEffect(() => {
        setSourceTab(SourceTab.REFERRING_DOMAIN)
        setDeviceTab(DeviceTab.BROWSER)
    }, [setDeviceTab, setSourceTab])

    return <App />
}

WebVitalsViewports.parameters = {
    pageUrl: '/web/web-vitals',
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2],
    testOptions: {
        includeNavigationInSnapshot: true,
        waitForLoadersToDisappear: true,
        viewportWidths: ALL_VIEWPORT_WIDTHS,
    },
}
export function WebVitalsViewports(): JSX.Element {
    return <App />
}

PageReportsViewports.parameters = {
    pageUrl: '/web/page-reports',
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2],
    testOptions: {
        includeNavigationInSnapshot: true,
        waitForLoadersToDisappear: true,
        viewportWidths: ALL_VIEWPORT_WIDTHS,
    },
}
export function PageReportsViewports(): JSX.Element {
    return <App />
}

HealthViewports.parameters = {
    pageUrl: urls.webAnalyticsHealth(),
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2, FEATURE_FLAGS.WEB_ANALYTICS_HEALTH_TAB],
    testOptions: {
        includeNavigationInSnapshot: true,
        // The health checks stay in their loading state without a live backend, so don't wait on
        // their loaders — capture the (deterministic) loading layout instead of timing out.
        waitForLoadersToDisappear: false,
        skipIframeWait: true,
        viewportWidths: ALL_VIEWPORT_WIDTHS,
    },
}
export function HealthViewports(): JSX.Element {
    return <App />
}

LiveViewports.parameters = {
    pageUrl: '/web/live',
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2, FEATURE_FLAGS.WEB_ANALYTICS_LIVE_METRICS],
    testOptions: {
        includeNavigationInSnapshot: true,
        // The live tab polls the user count every second (so it never reaches network idle) and
        // waits on a live stream that doesn't connect in storybook — capture its loading layout
        // rather than waiting on loaders that never settle.
        waitForLoadersToDisappear: false,
        skipIframeWait: true,
        viewportWidths: ALL_VIEWPORT_WIDTHS,
    },
}
export function LiveViewports(): JSX.Element {
    return <App />
}

BotAnalyticsViewports.parameters = {
    pageUrl: urls.webAnalyticsBotAnalytics(),
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2, FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS],
    testOptions: {
        includeNavigationInSnapshot: true,
        waitForLoadersToDisappear: true,
        viewportWidths: ALL_VIEWPORT_WIDTHS,
    },
}
export function BotAnalyticsViewports(): JSX.Element {
    return <App />
}

WebAnalyticsDashboardLoading.parameters = {
    layout: 'fullscreen',
    viewMode: 'story',
    mockDate: '2023-02-01',
    pageUrl: urls.webAnalytics(),
    featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2, FEATURE_FLAGS.WEB_ANALYTICS_TILE_SKELETONS],
    testOptions: {
        includeNavigationInSnapshot: true,
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr=web-analytics-skeleton-table], [data-attr=web-analytics-skeleton-chart]',
    },
    msw: {
        handlers: [],
    },
}
WebAnalyticsDashboardLoading.decorators = [
    mswDecorator({
        get: {
            '/stats': () => [200, { users_on_product: 2387 }],
            '/api/projects/:team_id/event_definitions': () => [200, { count: 5 }],
        },
        post: {
            '/api/environments/:team_id/query/:kind': () => new Promise<never>(() => {}),
        },
    }),
]
export function WebAnalyticsDashboardLoading(): JSX.Element {
    return <App />
}
