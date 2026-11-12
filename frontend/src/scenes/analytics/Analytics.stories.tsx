import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const ADA = {
    id: 1,
    uuid: 'user-ada',
    distinct_id: 'user-ada',
    first_name: 'Ada',
    last_name: 'Lovelace',
    email: 'ada@example.com',
}
const GRACE = {
    id: 7,
    uuid: 'user-grace',
    distinct_id: 'user-grace',
    first_name: 'Grace',
    last_name: 'Hopper',
    email: 'grace@example.com',
}

const at = (day: number, hour = 9): string =>
    `2026-09-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:00:00Z`

const CANVASES = [
    {
        id: 'canvas-1',
        name: 'Checkout funnel explorer',
        kind: 'freeform',
        description: '',
        channel: 'space-growth',
        template_id: 'freeform',
        generation_task_id: null,
        pinned: false,
        pinned_at: null,
        current_version_id: 'v1',
        published_build_id: 'b1',
        component_meta: null,
        created_by: GRACE,
        created_at: at(20),
        updated_at: at(27, 16),
        url: 'https://app.example.com/canvases/canvas-1',
    },
]

const DASHBOARDS = [
    {
        id: 12,
        name: 'Revenue overview',
        description: '',
        pinned: true,
        deleted: false,
        tags: ['finance', 'weekly'],
        created_by: ADA,
        created_at: at(2),
        last_accessed_at: at(28, 8),
        last_viewed_at: at(28, 8),
        folder: 'Finance',
        creation_mode: 'default',
        is_shared: false,
    },
    {
        id: 13,
        name: 'Activation',
        description: '',
        pinned: false,
        deleted: false,
        tags: ['growth'],
        created_by: GRACE,
        created_at: at(5),
        last_accessed_at: at(26),
        last_viewed_at: null,
        folder: 'Unfiled/Dashboards',
        creation_mode: 'default',
        is_shared: true,
    },
]

const NOTEBOOKS = [
    {
        short_id: 'nb-plan',
        title: 'Q4 experiment plan',
        deleted: false,
        created_by: ADA,
        created_at: at(10),
        last_modified_at: at(27, 11),
    },
]

const INSIGHTS = [
    {
        short_id: 'ins-signups',
        name: 'Signups by plan',
        derived_name: null,
        deleted: false,
        saved: true,
        tags: ['growth', 'onboarding', 'north-star', 'weekly'],
        created_by: ADA,
        created_at: at(1),
        last_modified_at: at(25),
        last_viewed_at: at(27, 18),
    },
    {
        short_id: 'ins-retention',
        name: null,
        derived_name: 'Weekly retention of paying users',
        deleted: false,
        saved: true,
        tags: [],
        created_by: GRACE,
        created_at: at(3),
        last_modified_at: at(22),
        last_viewed_at: null,
    },
]

const FILE_SYSTEM = [
    { id: 'fs-folder-finance', path: 'Finance', type: 'folder', depth: 1 },
    { id: 'fs-folder-growth', path: 'Growth', type: 'folder', depth: 1 },
    { id: 'fs-folder-unfiled', path: 'Unfiled', type: 'folder', depth: 1 },
    {
        id: 'fs-dash-12',
        path: 'Finance/Revenue overview',
        type: 'dashboard',
        ref: '12',
        href: '/dashboard/12',
        depth: 2,
        created_at: at(2),
        last_viewed_at: at(28, 8),
        meta: { created_by: ADA.id, tags: ['finance', 'weekly', 'board'] },
    },
    {
        id: 'fs-ins-signups',
        path: 'Growth/Signups by plan',
        type: 'insight/trends',
        ref: 'ins-signups',
        href: '/insights/ins-signups',
        depth: 2,
        created_at: at(1),
        last_viewed_at: at(27, 18),
        meta: { created_by: ADA.id },
    },
    {
        id: 'fs-nb-plan',
        path: 'Unfiled/Notebooks/Q4 experiment plan',
        type: 'notebook',
        ref: 'nb-plan',
        href: '/notebooks/nb-plan',
        depth: 3,
        created_at: at(10),
        last_viewed_at: at(27, 11),
        meta: { created_by: ADA.id },
    },
    {
        id: 'fs-canvas-1',
        path: 'Growth/Checkout funnel explorer',
        type: 'canvas',
        ref: 'canvas-1',
        href: '/canvases/canvas-1',
        depth: 2,
        created_at: at(20),
        last_viewed_at: at(26),
        meta: { created_by: GRACE.id, tags: ['growth'] },
    },
]

// Views and viewers over the last 30 days, by file system id, for the lists sorted on them.
const VIEW_COUNTS: Record<string, { view_count: number; viewer_count: number }> = {
    'fs-dash-12': { view_count: 42, viewer_count: 6 },
    'fs-ins-signups': { view_count: 17, viewer_count: 9 },
    'fs-canvas-1': { view_count: 8, viewer_count: 3 },
}

const VIEWERS = {
    since: '2026-08-30',
    results: [
        { user: ADA, view_count: 21, last_viewed_at: at(28, 8) },
        { user: GRACE, view_count: 12, last_viewed_at: at(27, 15) },
    ],
}

// Answers the file system like the API does for the params the Analyses pages send.
const fileSystemHandler = ({ request }: { request: Request }): [number, unknown] => {
    const params = new URL(request.url).searchParams
    const parent = params.get('parent')
    const depth = params.get('depth')
    const type = params.get('type')
    const typePrefix = params.get('type__startswith')
    const rawSearch = params.get('search')?.toLowerCase() ?? ''
    const createdByMe = rawSearch.includes('user:me')
    const search = rawSearch.replace('user:me', '').trim()
    const ref = params.get('ref')
    const results = FILE_SYSTEM.filter(
        (entry) =>
            (parent === null || entry.path.startsWith(`${parent}/`)) &&
            (depth === null || entry.depth === Number(depth)) &&
            (type === null || entry.type === type) &&
            (typePrefix === null || entry.type.startsWith(typePrefix)) &&
            (ref === null || entry.ref === ref) &&
            (!search || entry.path.toLowerCase().includes(search)) &&
            (!createdByMe || entry.meta?.created_by === ADA.id) &&
            (parent !== null || depth !== null || type !== null || typePrefix !== null || entry.type !== 'folder')
    )
    const orderBy = params.get('order_by')
    if (orderBy === '-view_count' || orderBy === '-viewer_count') {
        const counted = results
            .map((entry) => ({ ...entry, ...(VIEW_COUNTS[entry.id] ?? { view_count: 0, viewer_count: 0 }) }))
            .sort((first, second) =>
                orderBy === '-view_count'
                    ? second.view_count - first.view_count
                    : second.viewer_count - first.viewer_count
            )
        return [200, { results: counted, count: counted.length, next: null, users: [ADA, GRACE] }]
    }
    results.sort((first, second) => {
        if (orderBy === '-last_viewed_at' || orderBy === 'last_viewed_at') {
            if (!first.last_viewed_at) {
                return second.last_viewed_at ? 1 : 0
            }
            if (!second.last_viewed_at) {
                return -1
            }
            const difference = first.last_viewed_at.localeCompare(second.last_viewed_at)
            return orderBy === '-last_viewed_at' ? -difference : difference
        }
        return (second.created_at ?? '').localeCompare(first.created_at ?? '')
    })
    return [200, { results, count: results.length, next: null, users: [ADA, GRACE] }]
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Analytics',
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me/': { ...MOCK_DEFAULT_USER, ...ADA },
                '/api/projects/:team_id/task_channels/': [
                    { id: 'space-growth', name: 'growth', channel_type: 'public' },
                ],
                '/api/projects/:team_id/canvases/': { results: CANVASES, next: null, count: CANVASES.length },
                '/api/environments/:team_id/dashboards/': { results: DASHBOARDS, next: null, count: DASHBOARDS.length },
                '/api/projects/:team_id/dashboards/': { results: DASHBOARDS, next: null, count: DASHBOARDS.length },
                '/api/projects/:team_id/notebooks/': { results: NOTEBOOKS, next: null, count: NOTEBOOKS.length },
                '/api/environments/:team_id/insights/': { results: INSIGHTS, next: null, count: INSIGHTS.length },
                '/api/projects/:team_id/insights/': { results: INSIGHTS, next: null, count: INSIGHTS.length },
                '/api/environments/:team_id/file_system/': fileSystemHandler,
                '/api/projects/:team_id/file_system/': fileSystemHandler,
                '/api/projects/:team_id/file_system/viewers/': VIEWERS,
                '/api/projects/:team_id/tags/': {
                    results: ['finance', 'growth', 'onboarding', 'weekly'],
                    next: null,
                    count: 4,
                },
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'home-folder', path: 'Home' },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.analyticsList(),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<{}>

export const List: Story = {
    parameters: { pageUrl: urls.analyticsList() },
}

export const ListFiltered: Story = {
    parameters: { pageUrl: urls.analyticsList({ type: 'dashboard', createdBy: ['user-ada'] }) },
}

export const Mine: Story = {
    parameters: { pageUrl: urls.analyticsMine() },
}

export const Spaces: Story = {
    parameters: { pageUrl: urls.analyticsSpaces() },
}

export const ListNoMatches: Story = {
    parameters: { pageUrl: urls.analyticsList({ search: 'quarterly' }) },
}

export const ListEmpty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/file_system/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
    parameters: { pageUrl: urls.analyticsList() },
}

export const ListError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system/': () => [500, { detail: 'Server error' }],
                '/api/projects/:team_id/file_system/': () => [500, { detail: 'Server error' }],
            },
        }),
    ],
    parameters: { pageUrl: urls.analyticsList() },
}

const SIGNUPS_TRENDS = {
    id: 9001,
    short_id: 'aB3dE5fG',
    name: 'Daily signups',
    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
    result: [
        {
            count: 1284,
            data: [140, 162, 158, 171, 190, 214, 249],
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        },
    ],
}

export const ListCustomSidebar: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ui_customization/analytics_sidebar/': {
                    customized: true,
                    layout: {
                        version: 1,
                        sections: [
                            {
                                id: 'growth',
                                title: 'Growth',
                                icon: 'rocket',
                                items: [
                                    { type: 'metric', insight: SIGNUPS_TRENDS.short_id, label: 'Signups this week' },
                                    {
                                        type: 'link',
                                        to: { kind: 'dashboard', id: DASHBOARDS[0].id },
                                        label: 'Revenue overview',
                                        icon: 'dashboard',
                                    },
                                    { type: 'link', to: { kind: 'page', page: 'web_analytics' } },
                                    {
                                        type: 'button',
                                        to: { kind: 'page', page: 'new_insight' },
                                        label: 'New insight',
                                        variant: 'primary',
                                    },
                                ],
                            },
                            { id: 'pinned', title: 'Pinned', items: [{ type: 'list', source: 'pinned' }] },
                            { id: 'recents', title: 'Recents', items: [{ type: 'list', source: 'recents' }] },
                        ],
                    },
                },
                '/api/projects/:team_id/insights/': ({ request }) =>
                    new URL(request.url).searchParams.get('short_id') === SIGNUPS_TRENDS.short_id
                        ? [200, { results: [SIGNUPS_TRENDS], next: null, count: 1 }]
                        : [200, { results: INSIGHTS, next: null, count: INSIGHTS.length }],
            },
        }),
    ],
    parameters: {
        pageUrl: urls.analyticsList(),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.PHAI_SANDBOX_MODE, FEATURE_FLAGS.UI_CUSTOMIZATION],
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForSelector: '[data-attr="analytics-sidebar-metric"] >> text=1,284',
        },
    },
}

export const ListSpace: Story = {
    parameters: { pageUrl: urls.analyticsList({ folder: 'Growth' }) },
}

// Dialogs and menus render in portals outside the story canvas, so the helpers read the whole document.
async function clickWhenRendered(attr: string): Promise<void> {
    const element = await waitFor(
        () => {
            const found = document.querySelector<HTMLElement>(`[data-attr=${attr}]`)
            if (!found) {
                throw new Error(`${attr} is not rendered yet`)
            }
            return found
        },
        { timeout: 15000 }
    )
    await userEvent.click(element)
}

export const ListShareDialog: Story = {
    parameters: { pageUrl: urls.analyticsList() },
    play: async () => {
        await clickWhenRendered('analytics-list-row-share')
        await within(document.body).findAllByText('Finance', {}, { timeout: 15000 })
    },
}

export const ListNewInsightDialog: Story = {
    parameters: { pageUrl: urls.analyticsList() },
    play: async () => {
        await clickWhenRendered('analytics-list-new')
        await clickWhenRendered('analytics-new-insight')
        await within(document.body).findByText('How does it change over time?', {}, { timeout: 15000 })
    },
}

export const ListByViewers: Story = {
    parameters: { pageUrl: urls.analyticsList({ orderBy: '-viewer_count' }) },
}

export const ListViewersDialog: Story = {
    parameters: { pageUrl: urls.analyticsList({ orderBy: '-viewer_count' }) },
    play: async () => {
        await clickWhenRendered('analytics-list-row-viewers')
        await within(document.body).findByText('Last viewed', {}, { timeout: 15000 })
    },
}
