import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { App } from 'scenes/App'
import __dashboard1 from 'scenes/dashboard/__mocks__/dashboard1.json'
import __dashboards from 'scenes/dashboard/__mocks__/dashboards.json'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import type { DashboardTileBadge } from '~/types'

interface TileOverrides {
    badge?: DashboardTileBadge
    group_key?: string
}

const DASHBOARD_ID = 1
const HOG_SLID_UP_TRANSFORM = 'matrix(1, 0, 0, 1, 0, 0)'
const FIXED_REFRESH_TIME = '2023-02-01T00:00:00Z'
const FIXED_CACHE_TARGET_AGE = '2023-02-02T00:00:00Z'

function buildDashboard(
    tileOverrides: Record<number, TileOverrides>,
    customization?: Record<string, unknown>
): Record<string, unknown> {
    const fixture = __dashboard1 as unknown as { tiles: Record<string, any>[] } & Record<string, unknown>
    return {
        ...fixture,
        customization,
        tiles: fixture.tiles.map((tile) => ({
            ...tile,
            ...tileOverrides[tile.id],
            is_cached: true,
            insight: tile.insight && {
                ...tile.insight,
                last_refresh: FIXED_REFRESH_TIME,
                is_cached: true,
                cache_target_age: FIXED_CACHE_TARGET_AGE,
            },
        })),
    }
}

function dashboardMocks(dashboard: Record<string, unknown>): ReturnType<typeof mswDecorator> {
    const insights = (dashboard.tiles as Record<string, any>[]).flatMap((tile) => (tile.insight ? [tile.insight] : []))
    return mswDecorator({
        get: {
            '/api/environments/:team_id/dashboards/': __dashboards as any,
            [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
            '/api/environments/:team_id/insights/:id/': ({ params }) => {
                const insight = insights.find((candidate) => String(candidate.id) === params.id)
                return insight ? [200, insight] : [404, { detail: 'Insight not found' }]
            },
            '/api/environments/:team_id/session_recordings/': EMPTY_PAGINATED_RESPONSE,
            '/api/environments/:team_id/insights/my_last_viewed/': [],
            '/api/environments/:team_id/warehouse/variables/': [],
            '/api/projects/:team_id/events_retention/': [200, { retention_months: null, retained_from: null }],
        },
        post: {
            '/api/environments/:team_id/insights/cancel/': [201],
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Products/Dashboards/Tiles/Tile decorations',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.dashboard(DASHBOARD_ID),
    },
}
export default meta

type Story = StoryObj<{}>

export const WinnerWithGroupTitle: Story = {
    decorators: [
        dashboardMocks(
            buildDashboard(
                { 1: { badge: 'winner', group_key: 'launch' }, 2: { group_key: 'launch' } },
                { group_titles: { launch: 'Launch metrics' } }
            )
        ),
    ],
    parameters: {
        testOptions: {
            waitForSelector: ['.DashboardTileDecorations__crown', '.DashboardTileDecorations__group-title'],
        },
    },
}

export const CheekyHogOnHover: Story = {
    decorators: [dashboardMocks(buildDashboard({ 4: { badge: 'cheeky-hog' } }))],
    parameters: {
        testOptions: { waitForSelector: '.DashboardTileDecorations__hog' },
    },
    play: async () => {
        // A play function cannot move the real pointer, so no browser :hover applies. This copies the hover rule's effect.
        const hoverStyle = document.createElement('style')
        hoverStyle.textContent = '.react-grid-item .DashboardTileDecorations__hog img { transform: translateY(0); }'
        document.head.append(hoverStyle)
        await waitFor(() => {
            const hog = document.querySelector('.DashboardTileDecorations__hog img')
            if (!hog || getComputedStyle(hog).transform !== HOG_SLID_UP_TRANSFORM) {
                throw new Error('The hog has not finished sliding up')
            }
        })
    },
}
