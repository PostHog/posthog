import { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { App } from 'scenes/App'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { BaseMathType, DashboardMode, EntityTypes } from '~/types'

import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'

const dashboardRaw = require('./__mocks__/dashboard1.json')

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

const BASE_DASHBOARD_ID = 1
const SERVER_ERROR_DASHBOARD_ID = 2
const NOT_FOUND_DASHBOARD_ID = 1000

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': require('./__mocks__/dashboards.json'),
                [`/api/environments/:team_id/dashboards/${BASE_DASHBOARD_ID}/`]: dashboard,
                ...insightMocks,
                '/api/environments/:team_id/insights/:id/': insightFetchMock,
                [`/api/environments/:team_id/dashboards/${BASE_DASHBOARD_ID}/collaborators/`]: [],
                [`/api/environments/:team_id/dashboards/${SERVER_ERROR_DASHBOARD_ID}/`]: [
                    500,
                    { detail: 'Server error' },
                ],
                '/api/projects/:team_id/dashboard_templates/': require('./__mocks__/dashboard_templates.json'),
                '/api/projects/:team_id/dashboard_templates/json_schema/': require('./__mocks__/dashboard_template_schema.json'),
                '/api/environments/:team_id/dashboards/:dash_id/sharing/': {
                    created_at: '2023-02-25T13:28:20.454940Z',
                    enabled: false,
                    access_token: 'a-secret-token',
                },
                // Add variable data mock to prevent loading issues
                '/api/environments/:team_id/warehouse/variables/': [],
                // Add team endpoint
                '/api/environments/:team_id/': { id: BASE_DASHBOARD_ID, name: 'Test Team' },
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
        pageUrl: urls.dashboards(),
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const List: Story = {}

export const New = (): JSX.Element => {
    useAvailableFeatures([])
    useDelayedOnMountEffect(() => {
        newDashboardLogic.mount()
        newDashboardLogic.actions.showNewDashboardModal()
        dashboardTemplatesLogic.mount()
    })

    return <App />
}

export const NewSelectVariables = (): JSX.Element => {
    useAvailableFeatures([])
    useDelayedOnMountEffect(() => {
        newDashboardLogic.mount()
        newDashboardLogic.actions.showNewDashboardModal()
        newDashboardLogic.actions.setActiveDashboardTemplate({
            id: BASE_DASHBOARD_ID.toString(),
            template_name: 'Dashboard name',
            dashboard_description: 'The dashboard description',
            dashboard_filters: {},
            tiles: [],
            variables: [
                {
                    id: 'SIGN_UP',
                    name: 'Sign up page viewed',
                    type: 'event',
                    default: {
                        id: '$pageview',
                        math: BaseMathType.UniqueUsers,
                        type: EntityTypes.EVENTS,
                    },
                    required: true,
                    description: 'Add the current_url filter that matches your sign up page',
                },
                {
                    id: 'ACTIVATED',
                    name: 'Very very long event name very very long. Very very long event name very very long',
                    type: 'event',
                    default: {
                        id: '$pageview',
                        math: BaseMathType.UniqueUsers,
                        type: EntityTypes.EVENTS,
                    },
                    required: true,
                    description:
                        'Very long description. Select the event which best represents when a user is activated. Select the event which best represents when a user is activated',
                },
                {
                    id: 'ACTIVATED',
                    name: 'Activated event',
                    type: 'event',
                    default: {
                        id: '$pageview',
                        math: BaseMathType.UniqueUsers,
                        type: EntityTypes.EVENTS,
                    },
                    required: false,
                    description: 'Select the event which best represents when a user is activated',
                },
            ],
            tags: [],
            image_url: 'https://posthog.com/static/5e5cf65347bfb25f1dfc9792b18e87cb/6b063/posthog-bye-kubernetes.png',
        })
    })

    return <App />
}

export const Show: Story = {
    parameters: {
        pageUrl: urls.dashboard(BASE_DASHBOARD_ID),
    },
}

export const Edit = (): JSX.Element => {
    useDelayedOnMountEffect(() => {
        dashboardLogic({ id: BASE_DASHBOARD_ID }).mount()
        dashboardLogic({ id: BASE_DASHBOARD_ID }).actions.setDashboardMode(
            DashboardMode.Edit,
            DashboardEventSource.Browser
        )
    })

    return <App />
}
Edit.parameters = { pageUrl: urls.dashboard(BASE_DASHBOARD_ID) }

export const NotFound: Story = {
    parameters: {
        pageUrl: urls.dashboard(NOT_FOUND_DASHBOARD_ID),
    },
}

export const Erroring: Story = {
    parameters: {
        pageUrl: urls.dashboard(SERVER_ERROR_DASHBOARD_ID),
    },
}

// Access Control Dashboard Stories
const ACCESS_CONTROL_DASHBOARD_ID = 9999

const accessControlDashboard = {
    ...dashboard,
    id: ACCESS_CONTROL_DASHBOARD_ID,
    name: 'Access Control Demo Dashboard',
    description: 'Dashboard demonstrating different insight access levels',
    user_access_level: 'editor', // User has edit access to the dashboard
    tiles: [
        // Tile with no access insight
        {
            ...dashboard.tiles[0],
            id: 1001,
            insight: {
                ...dashboard.tiles[0].insight,
                id: 1001,
                short_id: 'no-access',
                name: 'Restricted Financial Data',
                description: 'This insight contains sensitive financial information.',
                user_access_level: 'none',
            },
        },
        // Tile with viewer access insight
        {
            ...dashboard.tiles[1],
            id: 1002,
            insight: {
                ...dashboard.tiles[1].insight,
                id: 1002,
                short_id: 'viewer-access',
                name: 'Public Metrics',
                description: 'General metrics available for viewing.',
                user_access_level: 'viewer',
            },
        },
        // Tile with editor access insight
        {
            ...dashboard.tiles[2],
            id: 1003,
            insight: {
                ...dashboard.tiles[2].insight,
                id: 1003,
                short_id: 'editor-access',
                name: 'Team Analytics',
                description: 'Analytics that the team can edit.',
                user_access_level: 'editor',
            },
        },
        // Tile with legacy insight (no access control)
        {
            ...dashboard.tiles[3],
            id: 1004,
            insight: {
                ...dashboard.tiles[3].insight,
                id: 1004,
                short_id: 'legacy-insight',
                name: 'Legacy Report',
                description: 'Old insight without access control.',
                // user_access_level is intentionally undefined
            },
        },
    ],
}

const accessControlInsightMocks = accessControlDashboard.tiles.reduce((acc: Record<string, any>, tile: any) => {
    if (tile.insight) {
        // Add both project and environment paths
        acc[`/api/projects/:team_id/insights/${tile.insight.id}/`] = tile.insight
        acc[`/api/environments/:team_id/insights/${tile.insight.id}/`] = tile.insight
    }
    return acc
}, {})

export const AccessControlDashboard: Story = {
    decorators: [
        mswDecorator({
            get: {
                ...accessControlInsightMocks,
                '/api/projects/:team_id/dashboards/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [accessControlDashboard],
                },
                [`/api/projects/:team_id/dashboards/${ACCESS_CONTROL_DASHBOARD_ID}/`]: accessControlDashboard,
                [`/api/environments/:team_id/dashboards/${ACCESS_CONTROL_DASHBOARD_ID}/`]: accessControlDashboard,
                [`/api/environments/:team_id/insights/:id/`]: insightFetchMock,
            },
        }),
    ],
    parameters: {
        pageUrl: urls.dashboard(ACCESS_CONTROL_DASHBOARD_ID),
    },
}

// Dashboard with no access (user can't edit dashboard but can view some insights)
const viewOnlyDashboard = {
    ...accessControlDashboard,
    id: ACCESS_CONTROL_DASHBOARD_ID + 1,
    name: 'View Only Dashboard',
    description: 'Dashboard where user has view access only',
    user_access_level: 'viewer', // User can only view the dashboard
}

export const ViewOnlyDashboard: Story = {
    decorators: [
        mswDecorator({
            get: {
                ...accessControlInsightMocks,
                '/api/projects/:team_id/dashboards/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [viewOnlyDashboard],
                },
                [`/api/projects/:team_id/dashboards/${ACCESS_CONTROL_DASHBOARD_ID + 1}/`]: viewOnlyDashboard,
                [`/api/environments/:team_id/dashboards/${ACCESS_CONTROL_DASHBOARD_ID + 1}/`]: viewOnlyDashboard,
                [`/api/environments/:team_id/insights/:id/`]: insightFetchMock,
            },
        }),
    ],
    parameters: {
        pageUrl: urls.dashboard(ACCESS_CONTROL_DASHBOARD_ID + 1),
    },
}
