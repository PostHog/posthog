import type { Meta, StoryObj } from '@storybook/react'

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
    {
        id: 'fs-dash-12',
        path: 'Finance/Revenue overview',
        type: 'dashboard',
        ref: '12',
        href: '/dashboard/12',
        depth: 2,
        created_at: at(2),
        last_viewed_at: at(28, 8),
        meta: { created_by: ADA.id },
    },
    {
        id: 'fs-ins-signups',
        path: 'Unfiled/Insights/Signups by plan',
        type: 'insight/trends',
        ref: 'ins-signups',
        href: '/insights/ins-signups',
        depth: 3,
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
        path: 'Unfiled/Canvases/Checkout funnel explorer',
        type: 'canvas',
        ref: 'canvas-1',
        href: '/canvases/canvas-1',
        depth: 3,
        created_at: at(20),
        last_viewed_at: at(26),
        meta: { created_by: GRACE.id },
    },
]

const fileSystemHandler = ({ request }: { request: Request }): [number, unknown] => {
    const params = new URL(request.url).searchParams
    const parent = params.get('parent')
    const results =
        parent !== null
            ? FILE_SYSTEM.filter(
                  (entry) =>
                      entry.path.startsWith(parent ? `${parent}/` : '') &&
                      entry.depth === (parent ? parent.split('/').length : 0) + 1
              )
            : FILE_SYSTEM.filter((entry) => entry.type !== 'folder')
    return [200, { results, count: results.length, users: [ADA, GRACE] }]
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Analytics',
    decorators: [
        mswDecorator({
            get: {
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
                '/api/projects/:team_id/tags/': ['finance', 'growth', 'onboarding', 'weekly'],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.analytics(),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<{}>

export const Home: Story = {}

export const HomeEmpty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/file_system/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

export const List: Story = {
    parameters: { pageUrl: urls.analyticsList() },
}

export const ListFiltered: Story = {
    parameters: { pageUrl: urls.analyticsList({ type: 'dashboard', createdBy: 'user-ada', tags: ['finance'] }) },
}

export const ListNoMatches: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/canvases/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/dashboards/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/notebooks/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
    parameters: { pageUrl: urls.analyticsList({ search: 'quarterly' }) },
}

export const ListEmpty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/canvases/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/dashboards/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/notebooks/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
    parameters: { pageUrl: urls.analyticsList() },
}

export const ListError: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/canvases/': () => [500, { detail: 'Server error' }],
                '/api/projects/:team_id/dashboards/': () => [500, { detail: 'Server error' }],
                '/api/projects/:team_id/notebooks/': () => [500, { detail: 'Server error' }],
                '/api/projects/:team_id/insights/': () => [500, { detail: 'Server error' }],
            },
        }),
    ],
    parameters: { pageUrl: urls.analyticsList() },
}

export const ListFolder: Story = {
    parameters: { pageUrl: urls.analyticsList({ folder: '' }) },
}
