import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const dashboardRaw = require('../dashboard/__mocks__/dashboard1.json')
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
    title: 'Scenes-App/Project Homepage',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': require('../dashboard/__mocks__/dashboards.json'),
                '/api/environments/:team_id/dashboards/1/': dashboard,
                ...insightMocks,
                '/api/environments/:team_id/insights/:id/': insightFetchMock,
                '/api/environments/:team_id/dashboards/1/collaborators/': [],
                '/api/environments/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/insights/my_last_viewed/': [],
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
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.projectHomepage(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const ProjectHomepage: Story = {}

const teamWithNoPrimaryDashboard = { ...MOCK_DEFAULT_TEAM, primary_dashboard: null }

function NoPrimaryDashboardStory(): JSX.Element {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)

    useEffect(() => {
        loadCurrentTeamSuccess(teamWithNoPrimaryDashboard)
    }, [loadCurrentTeamSuccess])

    return <App />
}

export const NoPrimaryDashboard: Story = {
    parameters: {
        docs: {
            description: {
                story: 'When primary_dashboard is null (e.g. after deletion), the homepage should show the NewTabScene search fallback — not a "not found" error.',
            },
        },
    },
    render: () => <NoPrimaryDashboardStory />,
}
