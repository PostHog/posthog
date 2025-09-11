import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const dashboardRaw = require('../../scenes/dashboard/__mocks__/dashboard1.json')
// Mark all tiles as cached to prevent refresh attempts in storybook
const dashboard = {
    ...dashboardRaw,
    tiles: dashboardRaw.tiles.map((tile: any) => ({
        ...tile,
        is_cached: true,
        ...(tile.insight
            ? {
                  insight: {
                      ...tile.insight,
                      last_refresh: new Date().toISOString(),
                      is_cached: true,
                      cache_target_age: new Date(Date.now() + 3600000).toISOString(), // 1 hour from now
                  },
              }
            : {}),
    })),
}

const insightMocks = dashboard.tiles.reduce((acc: Record<string, any>, tile: any) => {
    if (tile.insight) {
        // Add both the old project-based path and the new environment-based path
        acc[`/api/projects/:team_id/insights/${tile.insight.id}/`] = tile.insight
        acc[`/api/environments/:team_id/insights/${tile.insight.id}/`] = tile.insight
    }
    return acc
}, {})

// Add the generic insight fetching endpoint that requires from_dashboard param
const insightFetchMock = (req: any): [number, any] => {
    const insightId = req.params.id

    // Don't require from_dashboard in storybook to simplify things
    // Find the insight in the dashboard tiles
    const tile = dashboard.tiles?.find((t: any) => t.insight?.id?.toString() === insightId?.toString())
    if (tile?.insight) {
        return [200, tile.insight]
    }

    // Fallback to checking our insight mocks
    const insight =
        insightMocks[`/api/environments/:team_id/insights/${insightId}/`] ||
        insightMocks[`/api/projects/:team_id/insights/${insightId}/`]
    if (insight) {
        return [200, insight]
    }

    return [404, { detail: 'Insight not found' }]
}

const meta: Meta = {
    component: App,
    title: 'PostHog 3000/Navigation',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': require('../../scenes/dashboard/__mocks__/dashboards.json'),
                '/api/environments/:team_id/dashboards/1/': dashboard,
                ...insightMocks,
                '/api/environments/:team_id/insights/:id/': insightFetchMock,
                '/api/environments/:team_id/dashboards/1/collaborators/': [],
                '/api/environments/:team_id/insights/my_last_viewed/': require('../../scenes/saved-insights/__mocks__/insightsMyLastViewed.json'),
                '/api/environments/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/insight_variables/': EMPTY_PAGINATED_RESPONSE,
                // Add variable data mock to prevent loading issues
                '/api/environments/:team_id/warehouse/variables/': [],
                // Add team endpoint
                '/api/environments/:team_id/': { id: 1, name: 'Test Team' },
            },
            post: {
                '/api/environments/:team_id/insights/cancel/': [201],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
            snapshotBrowsers: ['chromium'],
        },
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.projectHomepage(),
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const NavigationBase: Story = {}
