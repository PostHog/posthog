import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'

import __dashboard1 from 'products/dashboards/frontend/__mocks__/dashboard1.json'

const DASHBOARD_ID = 22
// Two rows, so every tile is on the first screen. A tile below it waits to scroll into view and keeps its loader.
const TILE_COUNT = 8
const COLUMNS = 4
const TILE_WIDTH = 3
const TILE_HEIGHT = 5
const LAST_REFRESH = '2023-01-31T23:30:00Z'
const CACHE_TARGET_AGE = '2099-01-01T00:00:00Z'

const dashboardRaw = __dashboard1 as any
const sourceInsights = dashboardRaw.tiles.map((tile: any) => tile.insight)

// Each tile reuses one of the fixture insights, so every chart type in it shows up in the grid.
const insights = Array.from({ length: TILE_COUNT }, (_, index) => {
    const source = sourceInsights[index % sourceInsights.length]
    return {
        ...source,
        id: 2200 + index,
        short_id: `cached-${index}`,
        name: `${source.name} ${index + 1}`,
        order: index,
        dashboards: [DASHBOARD_ID],
        dashboard_tiles: [{ id: 22000 + index, dashboard_id: DASHBOARD_ID, deleted: false }],
        is_cached: true,
        last_refresh: LAST_REFRESH,
        cache_target_age: CACHE_TARGET_AGE,
    }
})

const tile = (insight: any, index: number): any => ({
    id: 22000 + index,
    order: index,
    color: null,
    text: null,
    is_cached: true,
    insight,
    layouts: {
        sm: {
            x: (index % COLUMNS) * TILE_WIDTH,
            y: Math.floor(index / COLUMNS) * TILE_HEIGHT,
            w: TILE_WIDTH,
            h: TILE_HEIGHT,
            minW: 3,
            minH: 5,
        },
        xs: { x: 0, y: index * TILE_HEIGHT, w: 1, h: TILE_HEIGHT, minW: 1, minH: 5 },
    },
})

const dashboard = {
    ...dashboardRaw,
    id: DASHBOARD_ID,
    name: 'Cached dashboard',
    tiles: insights.map(tile),
}

// Every tile is cached for the new date range too, so one request returns them all.
const cachedTilesResponse = ({ request }: MockResolverInfo): [number, any] => {
    const tileIds = (new URL(request.url).searchParams.get('tile_ids') ?? '').split(',').map(Number)
    return [
        200,
        {
            results: tileIds.map((tileId) => {
                const cachedTile = dashboard.tiles.find((candidate: any) => candidate.id === tileId)
                if (!cachedTile) {
                    return { id: tileId, status: 'not_found' }
                }
                const { id, result, last_refresh, cache_target_age } = cachedTile.insight
                return {
                    id: tileId,
                    status: 'hit',
                    insight: { id, result, last_refresh, cache_target_age, is_cached: true },
                }
            }),
        },
    ]
}

// A tile that loaded on its own would keep its loader, and the snapshot would wait on it.
const insightNeverLoads = (): Promise<[number, any]> => new Promise(() => {})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Dashboards/Cached tiles',
    decorators: [
        mswDecorator({
            get: {
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/cached_tiles/`]: cachedTilesResponse,
                [`/api/projects/:team_id/dashboards/${DASHBOARD_ID}/cached_tiles/`]: cachedTilesResponse,
                '/api/environments/:team_id/insights/:id/': insightNeverLoads,
                '/api/projects/:team_id/insights/:id/': insightNeverLoads,
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
            waitForSelector: '[data-attr="dashboard-items-action-refresh"]:has-text("Refresh")',
        },
    },
}
export default meta

type Story = StoryObj<{}>

/** With dashboard-v2, a date change on a cached dashboard shows every tile from one cached-tiles request. */
export const DateChangeShowsCachedTilesFromOneRequest: Story = {
    play: async () => {
        const logic = await waitFor(
            () => {
                const mounted = dashboardLogic.findMounted({ id: DASHBOARD_ID })
                if (!mounted?.values.dashboard || mounted.values.itemsLoading) {
                    throw new Error('Dashboard not loaded yet')
                }
                return mounted
            },
            { timeout: 10000 }
        )
        logic.actions.setDates('-7d', null)
    },
}
