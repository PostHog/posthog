import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { makeReport, mockSignals } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'

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
        created_by: { id: 1, first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
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
            output: { pr_url: 'https://github.com/example-org/webapp/pull/421' },
        },
        description_preview: 'Retry the billing webhook three times with a backoff before it reports a failure.',
        repository: 'example-org/webapp',
        created_by: { id: 179, first_name: 'John', last_name: 'Baker', email: 'john@example.com' },
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
        created_by: { id: 1, first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    },
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

// Today keeps sample mode, the open pane and the sidebar width in local storage, which outlives a story.
// Clearing it makes each story start clean, so only the sample stories show sample reports.
function clearTodayStorage(Story: () => JSX.Element): JSX.Element {
    for (const key of Object.keys(window.localStorage)) {
        if (/today/i.test(key)) {
            window.localStorage.removeItem(key)
        }
    }
    return <Story />
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
                          : []
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
                    count: 1,
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

export const SpacePage: Story = {
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
