import { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { Search } from './Search'
import { RECENTS_LIMIT, searchLogic } from './searchLogic'

const MOCK_RECENTS = {
    count: 5,
    results: [
        {
            id: '1',
            path: 'project://Insights/Weekly Active Users',
            type: 'insight',
            href: '/insights/abc123',
            last_viewed_at: '2024-01-15T10:30:00Z',
        },
        {
            id: '2',
            path: 'project://Dashboards/Marketing Overview',
            type: 'dashboard',
            href: '/dashboard/def456',
            last_viewed_at: '2024-01-14T14:20:00Z',
        },
        {
            id: '3',
            path: 'project://Feature Flags/new-onboarding',
            type: 'feature_flag',
            href: '/feature_flags/789',
            last_viewed_at: '2024-01-13T09:15:00Z',
        },
        {
            id: '4',
            path: 'project://Experiments/Pricing Page Test',
            type: 'experiment',
            href: '/experiments/exp123',
            last_viewed_at: '2024-01-12T16:45:00Z',
        },
        {
            id: '5',
            path: 'project://Notebooks/Q4 Analysis',
            type: 'notebook',
            href: '/notebooks/nb456',
            last_viewed_at: '2024-01-11T11:00:00Z',
        },
    ],
}

const MOCK_SCENE_LOG_VIEWS = [
    { ref: 'ProductAnalytics', viewed_at: '2024-01-15T10:00:00Z' },
    { ref: 'WebAnalytics', viewed_at: '2024-01-14T09:00:00Z' },
    { ref: 'SessionReplay', viewed_at: '2024-01-13T08:00:00Z' },
]

const meta: Meta = {
    title: 'Components/Search',
    component: Search.Root,
    tags: ['autodocs', 'test-skip'],
    parameters: {
        layout: 'centered',
    },
}
export default meta

function SearchWrapper({ loading = false }: { loading?: boolean }): JSX.Element {
    useEffect(() => {
        // Mount the logic and trigger initial load
        const logic = searchLogic({ logicKey: 'storybook' })
        logic.mount()

        return () => {
            logic.unmount()
        }
    }, [])

    return (
        <div className="w-[500px] h-[400px] border border-primary rounded overflow-hidden bg-surface-primary">
            <Search.Root logicKey="storybook" isActive showAskAiLink={false}>
                <Search.Input autoFocus={false} />
                <Search.Separator />
                <Search.Results />
            </Search.Root>
        </div>
    )
}

export const Loading: StoryFn = () => <SearchWrapper loading />
Loading.decorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/file_system/': async (_req, res, ctx) => {
                // Never resolve to keep showing skeletons
                await new Promise(() => {})
                return res(ctx.json(MOCK_RECENTS))
            },
            '/api/projects/:team_id/file_system_log_view/': async (_req, res, ctx) => {
                await new Promise(() => {})
                return res(ctx.json(MOCK_SCENE_LOG_VIEWS))
            },
        },
    }),
]
Loading.parameters = {
    testOptions: {
        waitForSelector: '[data-attr="wrapping-loading-skeleton"]',
    },
}

export const WithResults: StoryFn = () => <SearchWrapper />
WithResults.decorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/file_system/': MOCK_RECENTS,
            '/api/projects/:team_id/file_system_log_view/': MOCK_SCENE_LOG_VIEWS,
        },
    }),
]
WithResults.parameters = {
    testOptions: {
        waitForSelector: '.Autocomplete-List',
    },
}

export const SkeletonsWithInset: StoryFn = () => {
    return (
        <div className="w-[500px] p-4 bg-surface-primary border border-primary rounded">
            <p className="text-sm text-secondary mb-4">
                Loading skeletons with inset prop - note the gaps between rows
            </p>
            <div className="flex flex-col">
                {Array.from({ length: RECENTS_LIMIT }).map((_, i) => (
                    <div key={i} className="px-1">
                        <div className="py-0.5">
                            <div className="wrapping-loading-skeleton rounded h-8 w-full" />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
SkeletonsWithInset.parameters = {
    testOptions: {
        waitForSelector: '.wrapping-loading-skeleton',
    },
}
