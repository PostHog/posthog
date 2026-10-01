import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { ReactNode } from 'react'

import { Card } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { sessionPreview, spacePreview } from '~/layout/today/todayPreviewCards'
import { DEFAULT_RECENT_FILTERS } from '~/layout/today/todayRecentFilters'
import { TodaySessionHoverCard } from '~/layout/today/TodaySessionHoverCard'
import { todaySessionSelectionLogic } from '~/layout/today/todaySessionSelectionLogic'
import { TodaySpaceHoverCard } from '~/layout/today/TodaySpaceHoverCard'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { sessionItem } from '~/layout/today/todayWorkItems'
import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { makeReport, mockSignals } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { ChannelDTOApi, TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'

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

const SPACES = [
    {
        id: 'space-me',
        name: 'me',
        channel_type: 'personal',
        github_integration: null,
        repositories: [],
        auto_archive_after_days: null,
        created_at: '2026-09-01T09:00:00Z',
        starred: true,
        system_role: 'personal',
    },
    {
        id: 'space-general',
        name: 'general',
        channel_type: 'public',
        github_integration: null,
        repositories: [],
        auto_archive_after_days: null,
        created_at: '2026-09-01T09:00:00Z',
        starred: false,
        system_role: 'general',
    },
    {
        id: 'space-checkout',
        name: 'checkout',
        channel_type: 'public',
        github_integration: null,
        repositories: ['example-org/web', 'example-org/billing'],
        auto_archive_after_days: null,
        created_at: '2026-09-02T09:00:00Z',
        created_by: ADA,
        starred: true,
        system_role: null,
    },
]

const CONVERSATIONS = [
    {
        id: 'chat-1',
        title: 'Why did signups spike on Monday?',
        status: 'idle',
        type: 'assistant',
        updated_at: '2026-09-28T16:10:00Z',
    },
    {
        id: 'chat-2',
        title: 'Weekly retention by plan',
        status: 'idle',
        type: 'assistant',
        updated_at: '2026-09-25T09:00:00Z',
    },
]

const PINNED_SESSIONS = [
    {
        id: 'task-pinned',
        title: 'Fix the flaky checkout test',
        archived: false,
        last_activity_at: '2026-09-28T17:40:00Z',
        latest_run: { id: 'run-pinned', status: 'in_progress', environment: 'cloud', output: null },
        channel: 'space-checkout',
        description_preview: 'The checkout test fails about once in ten runs. Find the race and make the test stable.',
        repository: 'example-org/webapp',
        created_by: { id: 1, uuid: 'user-ada', first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    },
]

const RECENT_SESSIONS = [
    ...PINNED_SESSIONS,
    {
        id: 'task-1',
        channel: 'space-checkout',
        title: 'Add a retry to the billing webhook',
        archived: false,
        last_activity_at: '2026-09-28T18:05:00Z',
        latest_run: {
            id: 'run-1',
            status: 'completed',
            environment: 'cloud',
            output: {
                pr_url: 'https://github.com/example-org/webapp/pull/421',
                pr_urls: [
                    'https://github.com/example-org/webapp/pull/422',
                    'https://github.com/example-org/webapp/pull/423',
                ],
            },
        },
        description_preview: 'Retry the billing webhook three times with a backoff before it reports a failure.',
        repository: 'example-org/webapp',
        created_by: { id: 179, uuid: 'user-john', first_name: 'John', last_name: 'Baker', email: 'john@example.com' },
    },
    {
        id: 'task-3',
        channel: 'space-checkout',
        title: 'Speed up the invoice export',
        archived: false,
        last_activity_at: '2026-09-28T15:30:00Z',
        latest_run: {
            id: 'run-3',
            status: 'completed',
            environment: 'cloud',
            output: { pr_url: 'https://github.com/example-org/billing/pull/88' },
        },
        description_preview: 'The monthly invoice export takes minutes for large teams. Batch the queries.',
        repository: 'example-org/billing',
        created_by: { id: 42, first_name: 'Grace', last_name: 'Hopper', email: 'grace@example.com' },
    },
    {
        id: 'task-2',
        channel: 'space-checkout',
        title: 'Investigate the drop in trial starts',
        archived: false,
        last_activity_at: '2026-09-27T11:20:00Z',
        latest_run: { status: 'failed', environment: 'cloud', output: null },
        description_preview: 'Trial starts dropped last week. Find the step where people leave.',
        repository: null,
        created_by: { id: 1, uuid: 'user-ada', first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    },
]

// The unfiltered team-wide page the sidebar reads presence from: a teammate is working in the space right now.
const TEAM_SESSIONS = [
    {
        id: 'task-teammate',
        channel: 'space-checkout',
        title: 'Speed up the checkout page',
        archived: false,
        last_activity_at: '2026-09-28T18:28:00Z',
        latest_run: { id: 'run-teammate', status: 'in_progress', environment: 'cloud', output: null },
        description_preview: 'The checkout page takes too long to load. Find the slow requests.',
        repository: 'example-org/webapp',
        created_by: { id: 7, uuid: 'user-grace', first_name: 'Grace', last_name: 'Hopper', email: 'grace@example.com' },
    },
    ...RECENT_SESSIONS,
]

function canvas(
    id: string,
    name: string,
    description: string,
    updatedAt: string,
    author: typeof ADA
): Record<string, unknown> {
    return {
        id,
        name,
        kind: 'freeform',
        description,
        channel: 'space-checkout',
        template_id: '',
        generation_task_id: null,
        pinned: false,
        pinned_at: null,
        current_version_id: null,
        published_build_id: null,
        component_meta: null,
        created_by: author,
        created_at: '2026-09-20T09:00:00Z',
        updated_at: updatedAt,
        url: `/canvases/${id}`,
    }
}

const CANVASES = [
    canvas(
        'canvas-funnel',
        'Checkout funnel board',
        'Conversion from cart to paid, split by plan and country.',
        '2026-09-28T17:10:00Z',
        GRACE
    ),
    canvas('canvas-refunds', 'Refund tracker', '', '2026-09-26T08:45:00Z', ADA),
]

const LIBRARY = [
    { id: 'fs-1', path: 'Unfiled/Insights/Checkout funnel', type: 'insight', ref: 'abc123' },
    { id: 'fs-2', path: 'Unfiled/Dashboards/Growth overview', type: 'dashboard', ref: '12' },
    { id: 'fs-3', path: 'Unfiled/Feature flags/one-page-checkout', type: 'feature_flag', ref: '7' },
]

const REPORTS = [
    makeReport({
        id: 'report-1',
        title: 'Signup form rejects plus-addressed emails',
        summary:
            'Sign-ups with a plus sign in the email address fail validation since the last release.\n\n## Impact\n\nNew teams that use plus addressing cannot finish signing up.',
        status: SignalReportStatus.READY,
        signal_count: 12,
        updated_at: '2026-09-28T07:00:00Z',
        priority: 'P1',
        actionability: 'immediately_actionable',
        source_products: ['error_tracking', 'session_replay'],
        implementation_pr_url: 'https://github.com/example/app/pull/42',
    }),
    makeReport({
        id: 'report-2',
        title: 'Pricing page visitors drop off at the plan table',
        summary: 'Most visitors who reach the plan table leave without starting a trial.',
        status: SignalReportStatus.READY,
        signal_count: 5,
        updated_at: '2026-09-27T16:00:00Z',
        priority: 'P3',
        actionability: 'requires_human_input',
        source_products: ['analytics'],
        suggested_prompts: [
            'Which plans do visitors compare before they leave?',
            'Draft an experiment for the plan table',
        ],
    }),
    makeReport({
        id: 'report-3',
        title: 'LLM costs doubled for the summarize tool',
        summary: 'Token usage for the summarize tool doubled after the prompt change.',
        status: SignalReportStatus.PENDING_INPUT,
        signal_count: 3,
        updated_at: '2026-09-27T10:00:00Z',
        priority: 'P2',
        actionability: 'immediately_actionable',
        source_products: ['llm_analytics'],
    }),
]

// Today keeps sample mode, the open pane, the sidebar width and the space feed view in local storage, which outlives
// a story. Clearing it makes each story start clean, so only the sample stories show sample reports.
function clearTodayStorage(Story: () => JSX.Element): JSX.Element {
    for (const key of Object.keys(window.localStorage)) {
        if (/today|spaceFeedViewLogic/i.test(key)) {
            window.localStorage.removeItem(key)
        }
    }
    return <Story />
}

/** Starts a story with a saved space feed view, the way a returning person sees it. */
function withSpaceFeedView(saved: Record<string, unknown>): (Story: () => JSX.Element) => JSX.Element {
    return function SpaceFeedViewDecorator(Story) {
        for (const [reducer, value] of Object.entries(saved)) {
            window.localStorage.setItem(`products.tasks.spaces.spaceFeedViewLogic.${reducer}`, JSON.stringify(value))
        }
        return <Story />
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Project Homepage/Today',
    // No snapshots while the Today layout is still changing quickly. The stories stay for local development.
    tags: ['test-skip'],
    decorators: [
        clearTodayStorage,
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: REPORTS, count: 7 },
                '/api/projects/:team_id/signals/reports/:id/': (req) => [
                    200,
                    REPORTS.find((report) => report.id === req.params.id) ?? REPORTS[0],
                ],
                '/api/projects/:team_id/signals/reports/:id/signals/': (req) => [
                    200,
                    // Error tracking signals fetch their issue, which these stories do not mock.
                    {
                        signals: mockSignals(String(req.params.id), 6).filter(
                            (signal) => signal.source_product !== 'error_tracking'
                        ),
                    },
                ],
                '/api/projects/:team_id/task_channels/': SPACES,
                '/api/projects/:team_id/task_channels/:id/': (req) => [
                    200,
                    SPACES.find((space) => space.id === req.params.id) ?? SPACES[0],
                ],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const results = params.get('pinned')
                        ? PINNED_SESSIONS
                        : params.get('created_by') || params.get('channel') === 'space-checkout'
                          ? RECENT_SESSIONS
                          : params.get('channel')
                            ? []
                            : TEAM_SESSIONS
                    return [200, { results, count: results.length, next: null, previous: null }]
                },
                '/api/projects/:team_id/canvases/': ({ request }) => {
                    const results =
                        new URL(request.url).searchParams.get('channel') === 'space-checkout' ? CANVASES : []
                    return [200, { results, count: results.length, next: null, previous: null }]
                },
                '/api/projects/:team_id/task_activity/': {
                    results: [
                        {
                            id: 'activity-task-2',
                            task_id: 'task-2',
                            task_title: 'Investigate the drop in trial starts',
                            channel_id: 'space-checkout',
                            channel_name: 'checkout',
                            activity_at: '2026-09-28T17:00:00Z',
                            activity_kind: 'completed',
                            snippet: '',
                            latest_comment_id: null,
                            is_unread: true,
                        },
                    ],
                    unread_count: 1,
                    next_before: null,
                },
                '/api/environments/:team_id/conversations/': { results: CONVERSATIONS, next: null },
                '/api/environments/:team_id/file_system/': ({ request }) => {
                    const type = new URL(request.url).searchParams.get('type')
                    const results = type ? LIBRARY.filter((entry) => entry.type === type) : LIBRARY
                    return [200, { results, count: results.length }]
                },
                '/api/environments/:team_id/file_system/unfiled/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/tasks/summaries/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'task-1',
                            latest_run: {
                                pr_url: 'https://github.com/example-org/webapp/pull/421',
                                pr_state: 'merged',
                            },
                        },
                        {
                            id: 'task-3',
                            latest_run: { pr_url: 'https://github.com/example-org/billing/pull/88', pr_state: 'open' },
                        },
                    ],
                },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.projectHomepage(),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS],
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<{}>

export const Home: Story = {}

export const HomeWithSampleReports: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?sample=1` },
}

export const SampleReportPage: Story = {
    parameters: { pageUrl: `${urls.todayReport('sample-pr')}?sample=1` },
}

export const HomeWithNoReports: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/signals/reports/': EMPTY_PAGINATED_RESPONSE },
        }),
    ],
}

export const HomeWhenReportsFailToLoad: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/signals/reports/': () => [500, { detail: 'Server error' }] },
        }),
    ],
}

export const ReportWithPullRequest: Story = {
    parameters: { pageUrl: urls.todayReport('report-1') },
}

export const ReportWithSuggestedPrompts: Story = {
    parameters: { pageUrl: urls.todayReport('report-2') },
}

export const SpacesPane: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
    },
}

// Hovering a space row shows only its "…" menu, so the faces and the unread dot keep their place.
export const SpacesPaneHoveringSpaceRow: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByLabelText('Spaces'))
        const labels = await canvas.findAllByText('checkout')
        const row = labels.find((label) => label.closest('[data-attr="today-space-row"]'))
        if (row) {
            await userEvent.hover(row)
        }
    },
}

export const SpacePage: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

// A Cmd-click pick can't be held in a static story, so the play step selects a pinned and a recent row through the logic.
export const SpacesPaneWithSelectedSessions: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todaySessionSelectionLogic.actions.setSelection({ ids: ['task-pinned', 'task-1'], anchorId: 'task-1' })
    },
}

// The narrowed filters show their values in the primary color, and Clear filters shows at the end.
export const SpacesPaneWithRecentFilterMenu: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todaySpacesLogic.actions.setRecentFilters({ ...DEFAULT_RECENT_FILTERS, status: 'unread', environment: 'cloud' })
        await userEvent.click(await within(canvasElement).findByLabelText('Filters on'))
    },
}

export const SpacePageListView: Story = {
    decorators: [withSpaceFeedView({ view: 'list' })],
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

export const SpacePagePullRequests: Story = {
    decorators: [withSpaceFeedView({ types: ['pr'] })],
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

export const SpacePageCanvases: Story = {
    decorators: [withSpaceFeedView({ types: ['canvas'] })],
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

export const SpacePageCanvasesListView: Story = {
    decorators: [withSpaceFeedView({ types: ['canvas'], view: 'list' })],
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

export const SpacePageFiltered: Story = {
    decorators: [
        withSpaceFeedView({
            filters: { createdBy: 'anyone', sources: [], status: 'unread', pinned: 'any', environment: 'any' },
        }),
    ],
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

export const SpacesBrowse: Story = {
    parameters: { pageUrl: urls.taskSpaces() },
}

export const SpaceSettingsTab: Story = {
    parameters: { pageUrl: urls.taskSpaceSettings('space-checkout') },
}

export const LibraryAllObjects: Story = {
    parameters: { pageUrl: urls.library() },
}

export const LibraryFeatureFlags: Story = {
    parameters: { pageUrl: urls.library('feature_flag') },
}

export const ToolsPane: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Tools'))
    },
}

export const NarrowWindow: Story = {
    parameters: { testOptions: { viewport: { width: 800, height: 900 } } },
}

export const NarrowWindowWithSidebar: Story = {
    parameters: { testOptions: { viewport: { width: 800, height: 900 } } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Home'))
    },
}

// The card opens on hover, which a static story can't hold, so these render its contents in the same frame.
function HoverCardFrame({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="p-4">
            <Card size="sm" className="w-72 gap-0 border border-border py-0 shadow-md">
                {children}
            </Card>
        </div>
    )
}

export const SessionHoverCard: Story = {
    render: () => (
        <HoverCardFrame>
            <TodaySessionHoverCard
                preview={sessionPreview(
                    sessionItem({
                        ...RECENT_SESSIONS[1],
                        latest_run: {
                            ...RECENT_SESSIONS[1].latest_run,
                            output: {
                                pr_url: 'https://github.com/example-org/webapp/pull/421',
                                final_message:
                                    'The webhook now retries three times with a backoff. I opened a pull request with the change and a test for the failure case.',
                            },
                        },
                    } as unknown as TaskListItemApi),
                    {
                        unread: false,
                        pinned: true,
                        pullRequestStates: { 'https://github.com/example-org/webapp/pull/421': 'merged' },
                        spaceNames: { 'space-checkout': 'checkout' },
                    }
                )}
            />
        </HoverCardFrame>
    ),
}

export const SpaceHoverCard: Story = {
    render: () => (
        <HoverCardFrame>
            <TodaySpaceHoverCard
                preview={spacePreview(
                    {
                        ...SPACES[2],
                        repositories: ['example-org/web', 'example-org/billing', 'example-org/api', 'example-org/docs'],
                    } as ChannelDTOApi,
                    'checkout',
                    { people: [GRACE, ADA], liveUuids: [GRACE.uuid] },
                    '2026-09-28T18:28:00Z'
                )}
            />
        </HoverCardFrame>
    ),
}
