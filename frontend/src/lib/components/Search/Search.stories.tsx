import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import { Search } from './Search'

const MOCK_RECENTS = [
    {
        id: '1',
        path: 'My Dashboard',
        type: 'dashboard',
        ref: '1',
        href: '/dashboard/1',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    },
    {
        id: '2',
        path: 'Signup Funnel',
        type: 'insight/funnels',
        ref: '2',
        href: '/insights/2',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    },
    {
        id: '3',
        path: 'Weekly Active Users',
        type: 'insight/trends',
        ref: '3',
        href: '/insights/3',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    },
    {
        id: '4',
        path: 'Feature Flag: new-onboarding',
        type: 'feature_flag',
        ref: '4',
        href: '/feature_flags/4',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
    },
    {
        id: '5',
        path: 'User Retention',
        type: 'insight/retention',
        ref: '5',
        href: '/insights/5',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString(),
    },
]

const MOCK_PRODUCT_RECENTS = [
    {
        id: 'pr-1',
        path: 'Product analytics',
        type: 'product_analytics',
        ref: 'product_analytics',
        href: '/project/2/insights',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    },
    {
        id: 'pr-2',
        path: 'Web analytics',
        type: 'web_analytics',
        ref: 'web_analytics',
        href: '/project/2/web',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    },
    {
        id: 'pr-3',
        path: 'LLM analytics',
        type: 'llm_analytics',
        ref: 'llm_analytics',
        href: '/project/2/llm-analytics',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    },
    {
        id: 'pr-4',
        path: 'Surveys',
        type: 'surveys',
        ref: 'surveys',
        href: '/project/2/surveys',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    },
    {
        id: 'pr-5',
        path: 'Error tracking',
        type: 'error_tracking',
        ref: 'error_tracking',
        href: '/project/2/error_tracking',
        last_viewed_at: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
    },
]

const MOCK_PRODUCT_STARRED = [
    {
        id: 'st-1',
        path: 'Session replay',
        type: 'session_replay',
        ref: 'session_replay',
        href: '/project/2/replay',
    },
    {
        id: 'st-2',
        path: 'Feature flags',
        type: 'feature_flags',
        ref: 'feature_flags',
        href: '/project/2/feature_flags',
    },
    {
        id: 'st-3',
        path: 'Experiments',
        type: 'experiments',
        ref: 'experiments',
        href: '/project/2/experiments',
    },
    {
        id: 'st-4',
        path: 'Data warehouse',
        type: 'data_warehouse',
        ref: 'data_warehouse',
        href: '/project/2/data-warehouse',
    },
    {
        id: 'st-5',
        path: 'Workflows',
        type: 'workflows',
        ref: 'workflows',
        href: '/project/2/workflows',
    },
]

const MOCK_SEARCH_RESULTS = {
    results: [
        {
            result_id: '101',
            type: 'insight',
            rank: 1,
            extra_fields: { name: 'Weekly Active Users' },
        },
        {
            result_id: '102',
            type: 'insight',
            rank: 2,
            extra_fields: { name: 'User Signup Trend' },
        },
        {
            result_id: '201',
            type: 'dashboard',
            rank: 1,
            extra_fields: { name: 'User Overview Dashboard' },
        },
        {
            result_id: '301',
            type: 'feature_flag',
            rank: 1,
            extra_fields: { key: 'user-profiles-v2' },
        },
    ],
    counts: {
        insight: 2,
        dashboard: 1,
        feature_flag: 1,
    },
}

const meta: Meta = {
    title: 'Components/Search',
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<{}>

const SearchContainer = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <div className="grow w-[600px] border rounded-lg overflow-hidden bg-bg-light">{children}</div>
)

const SHARED_MOCKS = {
    '/api/environments/:team_id/file_system/log_view/': () => [200, []],
    '/api/environments/:team_id/persons/': () => [200, EMPTY_PAGINATED_RESPONSE],
    '/api/environments/:team_id/groups/': () => [200, EMPTY_PAGINATED_RESPONSE],
}

export const Default: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/file_system/': (_req, res, ctx) => {
                    return res(ctx.delay(10), ctx.json(toPaginatedResponse(MOCK_RECENTS)))
                },
                '/api/environments/:team_id/search/': () => [200, { results: [], counts: {} }],
                ...SHARED_MOCKS,
            },
        })

        return (
            <SearchContainer>
                <Search.Root logicKey="storybook-default" isActive showAskAiLink={false}>
                    <Search.Input autoFocus />
                    <Search.Separator />
                    <Search.Results />
                    <Search.Footer />
                </Search.Root>
            </SearchContainer>
        )
    },
    parameters: {
        docs: { description: { story: 'Shows 5 recent items and apps when no search query is entered.' } },
    },
}

export const ProductRecentsAndStarred: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/file_system/': (_req, res, ctx) => {
                    return res(ctx.delay(10), ctx.json(toPaginatedResponse(MOCK_PRODUCT_RECENTS)))
                },
                '/api/environments/:team_id/file_system_shortcut/': (_req, res, ctx) => {
                    return res(ctx.delay(10), ctx.json(toPaginatedResponse(MOCK_PRODUCT_STARRED)))
                },
                '/api/environments/:team_id/search/': () => [200, { results: [], counts: {} }],
                ...SHARED_MOCKS,
            },
        })

        return (
            <SearchContainer>
                <Search.Root logicKey="storybook-product-recents-starred" isActive showAskAiLink={false}>
                    <Search.Input autoFocus />
                    <Search.Separator />
                    <Search.Results />
                    <Search.Footer />
                </Search.Root>
            </SearchContainer>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'Recents and starred entries whose `type` matches an entry in `availableOnboardingProducts` render with the manifest brand colour (e.g. green for web analytics, purple for LLM analytics) instead of falling back to `currentColor`. Demonstrates the fix for product icons in recents/starred shortcuts.',
            },
        },
    },
}

export const Searching: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/file_system/': (_req, res, ctx) => {
                    return res(ctx.delay(10), ctx.json(toPaginatedResponse(MOCK_RECENTS)))
                },
                '/api/environments/:team_id/search/': (_req, res, ctx) => {
                    return res(ctx.delay(100), ctx.json(MOCK_SEARCH_RESULTS))
                },
                ...SHARED_MOCKS,
            },
        })

        return (
            <SearchContainer>
                <Search.Root logicKey="storybook-searching" isActive showAskAiLink={false} defaultSearchValue="user">
                    <Search.Input autoFocus />
                    <Search.Separator />
                    <Search.Results />
                    <Search.Footer />
                </Search.Root>
            </SearchContainer>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'Searching for "user": recents and apps are filtered client-side instantly, server results appear below without shifting existing items.',
            },
        },
    },
}
