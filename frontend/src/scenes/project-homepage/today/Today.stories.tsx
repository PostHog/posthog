import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const SPACES = [
    {
        id: 'space-me',
        name: 'me',
        channel_type: 'private',
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
        repositories: [],
        auto_archive_after_days: null,
        created_at: '2026-09-02T09:00:00Z',
        starred: true,
        system_role: null,
    },
]

const CONVERSATIONS = [
    { id: 'chat-1', title: 'Why did signups spike on Monday?', status: 'idle', type: 'assistant' },
    { id: 'chat-2', title: 'Weekly retention by plan', status: 'idle', type: 'assistant' },
]

const LIBRARY = [
    { id: 'fs-1', path: 'Unfiled/Insights/Checkout funnel', type: 'insight', ref: 'abc123' },
    { id: 'fs-2', path: 'Unfiled/Dashboards/Growth overview', type: 'dashboard', ref: '12' },
    { id: 'fs-3', path: 'Unfiled/Feature flags/one-page-checkout', type: 'feature_flag', ref: '7' },
]

const REPORTS = [
    {
        id: 'report-1',
        title: 'Signup form rejects plus-addressed emails',
        summary: 'Sign-ups with a plus sign in the email address fail validation since the last release.',
        status: 'ready',
        total_weight: 4,
        signal_count: 12,
        created_at: '2026-09-27T09:00:00Z',
        updated_at: '2026-09-28T07:00:00Z',
        artefact_count: 2,
        is_suggested_reviewer: true,
        priority: 'P1',
        source_products: ['error_tracking', 'session_replay'],
        implementation_pr_url: 'https://github.com/example/app/pull/42',
    },
    {
        id: 'report-2',
        title: 'Pricing page visitors drop off at the plan table',
        summary: 'Most visitors who reach the plan table leave without starting a trial.',
        status: 'ready',
        total_weight: 2,
        signal_count: 5,
        created_at: '2026-09-26T09:00:00Z',
        updated_at: '2026-09-27T16:00:00Z',
        artefact_count: 1,
        is_suggested_reviewer: false,
        priority: 'P3',
        source_products: ['analytics'],
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Project Homepage/Today',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/reports/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/task_channels/': SPACES,
                '/api/projects/:team_id/tasks/': EMPTY_PAGINATED_RESPONSE,
                '/api/environments/:team_id/conversations/': { results: CONVERSATIONS, next: null },
                '/api/environments/:team_id/file_system/': { results: LIBRARY, count: LIBRARY.length },
                '/api/environments/:team_id/file_system/unfiled/': { results: [], count: 0 },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.projectHomepage(),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<{}>

export const SampleHome: Story = {}

export const ReportPage: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?report=pr` },
}

export const ReportWithAdvisory: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?report=error` },
}

export const NewFlowCompose: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?view=new` },
}

export const RealReports: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: REPORTS, count: REPORTS.length },
            },
        }),
    ],
}

export const SpacesPane: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
    },
}

export const LibraryAllObjects: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?view=library` },
}

export const LibraryFeatureFlags: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?view=library&type=feature_flag` },
}

export const ToolsPane: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Tools'))
    },
}
