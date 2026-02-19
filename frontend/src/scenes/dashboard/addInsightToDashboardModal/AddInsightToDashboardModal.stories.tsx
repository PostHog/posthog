import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { addInsightToDashboardLogic } from '../addInsightToDashboardModalLogic'
import { dashboardLogic } from '../dashboardLogic'
import { AddInsightToDashboardModal } from './AddInsightToDashboardModal'

const dashboardRaw = require('../__mocks__/dashboard1.json')

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
                      cache_target_age: new Date(Date.now() + 3600000).toISOString(),
                  },
              }
            : {}),
    })),
}

const mockInsightsList = {
    results: dashboard.tiles
        .filter((tile: any) => tile.insight)
        .map((tile: any) => ({
            ...tile.insight,
            tags: tile.insight.tags || ['marketing'],
            description: tile.insight.description || 'A sample insight for testing',
        })),
    count: dashboard.tiles.filter((tile: any) => tile.insight).length,
    next: null,
    previous: null,
}

const DASHBOARD_ID = 1

const meta: Meta<typeof AddInsightToDashboardModal> = {
    component: AddInsightToDashboardModal,
    title: 'Scenes-App/Dashboards/Add Insight to Dashboard Modal',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': require('../__mocks__/dashboards.json'),
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
                '/api/environments/:team_id/insights/': mockInsightsList,
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
        testOptions: { waitForSelector: '.LemonModal' },
    },
}
export default meta

function ModalStory({ showMore = false }: { showMore?: boolean }): JSX.Element {
    addInsightToDashboardLogic.mount()
    addInsightToDashboardLogic.actions.showAddInsightToDashboardModal()
    if (showMore) {
        addInsightToDashboardLogic.actions.toggleShowMoreInsightTypes()
    }

    return (
        <BindLogic logic={dashboardLogic} props={{ id: DASHBOARD_ID }}>
            <AddInsightToDashboardModal />
        </BindLogic>
    )
}

export const Default: StoryFn = () => <ModalStory />

export const WithMoreInsightTypes: StoryFn = () => <ModalStory showMore />

export const Empty: StoryFn = () => <ModalStory />
Empty.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/dashboards/': require('../__mocks__/dashboards.json'),
            [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
            '/api/environments/:team_id/insights/': { results: [], count: 0, next: null, previous: null },
        },
        post: {
            '/api/environments/:team_id/insights/cancel/': [201],
        },
    }),
]
