import { Meta, StoryObj } from '@storybook/react'
import { delay, HttpResponse } from 'msw'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import type { MockResolverInfo } from '~/mocks/utils'
import { BaseMathType, EntityTypes } from '~/types'

import __dashboard1 from './__mocks__/dashboard1.json'
import __dashboard_template_schema from './__mocks__/dashboard_template_schema.json'
import __dashboard_templates from './__mocks__/dashboard_templates.json'
import __dashboards from './__mocks__/dashboards.json'
import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'

const dashboardRaw = __dashboard1 as any

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
const insightFetchMock = ({ params }: MockResolverInfo): [number, any] => {
    const insightId = params.id

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
const DASHBOARD_STATE_ID = 2

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': __dashboards as any,
                [`/api/environments/:team_id/dashboards/${BASE_DASHBOARD_ID}/`]: dashboard,
                ...insightMocks,
                '/api/environments/:team_id/insights/:id/': insightFetchMock,
                [`/api/environments/:team_id/dashboards/${BASE_DASHBOARD_ID}/collaborators/`]: [],
                '/api/projects/:team_id/dashboard_templates/': __dashboard_templates as any,
                '/api/projects/:team_id/dashboard_templates/json_schema/': __dashboard_template_schema as any,
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
        // Suppress async chart canvas painting so these dashboard snapshots are deterministic.
        testOptions: { skipCanvasDraw: true },
    },
}
export default meta

type Story = StoryObj<{}>
const DASHBOARD_STATES = ['Loading', 'Not Found', 'Access Denied', 'Server Error', 'Empty'] as const
type DashboardState = (typeof DASHBOARD_STATES)[number]

export const List: Story = {}

export const NewDashboardModal: Story = {
    render: () => {
        useAvailableFeatures([])
        useDelayedOnMountEffect(() => {
            newDashboardLogic.mount()
            newDashboardLogic.actions.showNewDashboardModal()
            dashboardTemplatesLogic.mount()
        })

        return <App />
    },
}

export const NewSelectVariables: Story = {
    render: () => {
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
                image_url:
                    'https://posthog.com/static/5e5cf65347bfb25f1dfc9792b18e87cb/6b063/posthog-bye-kubernetes.png',
            })
        })

        return <App />
    },
}

export const Show: Story = {
    parameters: {
        pageUrl: urls.dashboard(BASE_DASHBOARD_ID),
        testOptions: { snapshotBrowsers: [] },
    },
}

export const DashboardStates: StoryObj<{ state: DashboardState }> = {
    args: {
        state: 'Loading',
    },
    argTypes: {
        state: {
            control: 'select',
            options: DASHBOARD_STATES,
        },
    },
    render: ({ state }) => {
        let response: any

        switch (state) {
            case 'Not Found':
                response = [404, { detail: 'Not found.' }]
                break
            case 'Access Denied':
                response = [403, { code: 'permission_denied', detail: 'You do not have access to this dashboard.' }]
                break
            case 'Server Error':
                response = [500, { detail: 'Server error' }]
                break
            case 'Empty':
                response = { ...dashboard, id: DASHBOARD_STATE_ID, name: 'Empty dashboard', tiles: [] }
                break
            case 'Loading':
                response = async () => {
                    await delay('infinite')
                    return HttpResponse.json({})
                }
                break
        }

        useStorybookMocks({
            get: {
                [`/api/environments/:team_id/dashboards/${DASHBOARD_STATE_ID}/`]: response,
            },
        })

        return <App key={state} />
    },
    parameters: {
        pageUrl: urls.dashboard(DASHBOARD_STATE_ID),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[aria-label="Loading dashboard"]' },
    },
}
