import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsPieBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import __homeTabDashboard from '../dashboard/__mocks__/dashboard1.json'
import insightsJson from './__mocks__/insights.json'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

// Mark all tiles as cached so the embedded Dashboard doesn't attempt to refresh them in storybook.
const homeTabDashboardRaw = __homeTabDashboard as any
const homeTabDashboard = {
    ...homeTabDashboardRaw,
    tiles: homeTabDashboardRaw.tiles.map((tile: any) => ({
        ...tile,
        is_cached: true,
        ...(tile.insight
            ? {
                  insight: {
                      ...tile.insight,
                      last_refresh: new Date().toISOString(),
                      is_cached: true,
                      cache_target_age: new Date(Date.now() + 3600000).toISOString(),
                  },
              }
            : {}),
    })),
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Saved Insights',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-18',
        pageUrl: urls.insights(),
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 6).map((result, i) => ({
                        // Keep size of response in check
                        ...result,
                        query: insights[i % insights.length].query,
                        result: insights[i % insights.length].result,
                    }))
                ),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListView: Story = {}

export const Home: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'test' },
        pageUrl: `${urls.savedInsights()}?tab=home`,
        testOptions: { viewport: { width: 1300, height: 2000 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights/my_last_viewed/': [],
                '/api/environments/:team_id/insights/trending/': [],
                '/api/environments/:team_id/insights/activity': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/event_definitions/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/insights/': toPaginatedResponse(insightsJson.results.slice(0, 1)),
                '/api/projects/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
                '/api/environments/:team_id/persons/batch_by_distinct_ids/': { results: {} },
            },
        }),
    ],
}

export const HomeWithBooleanFlag: Story = {
    ...Home,
    parameters: {
        ...Home.parameters,
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: true },
    },
}

const teamWithHomeTabDashboard = { ...MOCK_DEFAULT_TEAM, home_tab_dashboard: homeTabDashboard.id }

function HomeWithDashboardStory(): JSX.Element | null {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const [ready, setReady] = useState(false)

    useLayoutEffect(() => {
        loadCurrentTeamSuccess(teamWithHomeTabDashboard)
        setReady(true)
    }, [loadCurrentTeamSuccess])

    if (!ready) {
        return null
    }

    return <App />
}

export const HomeWithDashboard: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'test' },
        pageUrl: `${urls.savedInsights()}?tab=home`,
        testOptions: { viewport: { width: 1300, height: 2000 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights/my_last_viewed/': [],
                '/api/environments/:team_id/insights/trending/': [],
                '/api/environments/:team_id/insights/activity': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/event_definitions/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/insights/': toPaginatedResponse(insightsJson.results.slice(0, 1)),
                '/api/projects/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
                [`/api/environments/:team_id/dashboards/${homeTabDashboard.id}/`]: homeTabDashboard,
                [`/api/environments/:team_id/dashboards/${homeTabDashboard.id}/collaborators/`]: [],
                '/api/environments/:team_id/warehouse/variables/': [],
                '/api/projects/:team_id/events_retention/': { retention_months: null },
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
                '/api/environments/:team_id/persons/batch_by_distinct_ids/': { results: {} },
            },
        }),
    ],
    render: () => <HomeWithDashboardStory />,
}

export const EmptyState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

export const ErrorState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': () => [500, { detail: 'Internal server error' }],
            },
        }),
    ],
}

export const SearchResults: Story = {
    parameters: {
        pageUrl: urls.savedInsights() + '?search=revenue',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 5).map((result, i) => {
                        const exactNames = ['Revenue by region', 'Weekly revenue']
                        const similarNames = ['Reveneu trends', 'Q4 reveue', 'Revanue dashboard']
                        const isExact = i < exactNames.length
                        return {
                            ...result,
                            name: isExact ? exactNames[i] : similarNames[i - exactNames.length],
                            query: insights[i % insights.length].query,
                            result: insights[i % insights.length].result,
                            search_match_type: isExact ? 'exact' : 'similar',
                        }
                    })
                ),
            },
        }),
    ],
}
