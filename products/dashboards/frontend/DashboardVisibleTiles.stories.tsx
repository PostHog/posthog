import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'

import __dashboard1 from 'products/dashboards/frontend/__mocks__/dashboard1.json'

const DASHBOARD_ID = 21
const TILE_COUNT = 24
const COLUMNS = 3
const TILE_WIDTH = 4
const TILE_HEIGHT = 5

const dashboardRaw = __dashboard1 as any
const sourceInsights = dashboardRaw.tiles.map((tile: any) => tile.insight)

// Each tile reuses one of the fixture insights, so every chart type in it shows up in the grid.
const insights = Array.from({ length: TILE_COUNT }, (_, index) => {
    const source = sourceInsights[index % sourceInsights.length]
    return {
        ...source,
        id: 2100 + index,
        short_id: `visible-${index}`,
        name: `${source.name} ${index + 1}`,
        order: index,
        dashboards: [DASHBOARD_ID],
        dashboard_tiles: [{ id: 21000 + index, dashboard_id: DASHBOARD_ID, deleted: false }],
    }
})

const tile = (insight: any, index: number): any => {
    const x = (index % COLUMNS) * TILE_WIDTH
    const y = Math.floor(index / COLUMNS) * TILE_HEIGHT
    return {
        id: 21000 + index,
        order: index,
        color: null,
        text: null,
        is_cached: false,
        // No cached result and no cache target age, so every tile needs a query.
        insight: { ...insight, result: null, last_refresh: null, cache_target_age: undefined },
        layouts: {
            sm: { x, y, w: TILE_WIDTH, h: TILE_HEIGHT, minW: 3, minH: 5 },
            xs: { x: 0, y: index * TILE_HEIGHT, w: 1, h: TILE_HEIGHT, minW: 1, minH: 5 },
        },
    }
}

const dashboard = {
    ...dashboardRaw,
    id: DASHBOARD_ID,
    name: 'Long dashboard',
    tiles: insights.map(tile),
}

const insightResponse = ({ params }: MockResolverInfo): [number, any] => {
    const insight = insights.find((candidate) => String(candidate.id) === String(params.id))
    return insight ? [200, insight] : [404, { detail: 'Insight not found' }]
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Dashboards/Visible tiles',
    decorators: [
        mswDecorator({
            get: {
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
                '/api/environments/:team_id/insights/:id/': insightResponse,
                '/api/projects/:team_id/insights/:id/': insightResponse,
                '/api/environments/:team_id/warehouse/variables/': [],
            },
            post: {
                '/api/environments/:team_id/insights/cancel/': [201],
                '/api/projects/:team_id/file_system/home_folder/': { id: 'home-folder', path: 'Home' },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.dashboard(DASHBOARD_ID),
        featureFlags: [FEATURE_FLAGS.DASHBOARD_V2, FEATURE_FLAGS.DASHBOARD_V2_USERS],
        testOptions: {
            // Tiles below the fold keep their placeholder until they scroll into view, and it counts as a loader.
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="dashboard-items-action-refresh"]:has-text("Refresh")',
        },
    },
}
export default meta

type Story = StoryObj<{}>

/** With dashboard-v2, the first screen of a long dashboard loads, and the tiles below it load once they scroll into view. */
export const OffscreenTilesWaitToLoad: Story = {}
