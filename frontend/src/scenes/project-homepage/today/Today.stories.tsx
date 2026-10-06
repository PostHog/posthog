import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { ReactNode } from 'react'

import { Card } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { briefingItemReportCard } from 'scenes/project-homepage/today/todayBriefingItems'
import { TodayReportHoverCard } from 'scenes/project-homepage/today/TodayReportHoverCard'
import { urls } from 'scenes/urls'

import { todayListAppearanceLogic } from '~/layout/today/todayListAppearanceLogic'
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
import {
    reportMetricQueryHandler,
    reportMetricsFixture,
} from 'products/signals/frontend/inbox/__mocks__/reportMetricMocks'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { ChannelDTOApi, TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'
import type { ReportPageApi } from 'products/today/frontend/generated/api.schemas'
import type { BriefingApi, BriefingItemApi } from 'products/today/frontend/generated/api.schemas'

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
        origin_product: 'slack',
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
        origin_product: 'error_tracking',
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
        origin_product: 'signal_report',
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

const USER = { id: 1, uuid: 'user-1', first_name: 'Ada', email: 'ada@example.com' }

const VIEW_CANVASES = [
    {
        id: 'canvas-1',
        name: 'Checkout health board',
        kind: 'freeform',
        channel: 'space-checkout',
        updated_at: '2026-09-28T17:50:00Z',
        current_version_id: 'version-1',
        generation_task_id: null,
    },
    {
        id: 'canvas-building',
        name: 'Signup funnel by country',
        kind: 'freeform',
        channel: 'space-checkout',
        updated_at: '2026-09-28T18:05:00Z',
        current_version_id: null,
        generation_task_id: 'task-canvas-building',
    },
    {
        id: 'canvas-2',
        name: 'Weekly growth widgets',
        kind: 'grid',
        channel: 'space-general',
        updated_at: '2026-09-26T08:15:00Z',
        current_version_id: 'version-1',
        generation_task_id: null,
    },
].map((canvas) => ({ description: '', pinned: false, created_by: USER, created_at: canvas.updated_at, ...canvas }))

const NOTEBOOKS = [
    { short_id: 'nb-1', title: 'Trial drop-off investigation', last_modified_at: '2026-09-28T12:30:00Z' },
    { short_id: 'nb-2', title: 'Q3 pricing research notes', last_modified_at: '2026-09-20T10:00:00Z' },
].map((notebook) => ({
    id: notebook.short_id,
    deleted: false,
    created_at: notebook.last_modified_at,
    created_by: USER,
    last_modified_by: USER,
    ...notebook,
}))

const DASHBOARDS = [
    { id: 12, name: 'Growth overview', last_viewed_at: '2026-09-28T09:00:00Z', created_at: '2026-08-01T09:00:00Z' },
    { id: 13, name: 'Billing and revenue', last_viewed_at: null, created_at: '2026-09-24T09:00:00Z' },
].map((dashboard) => ({ description: '', pinned: false, deleted: false, tags: [], created_by: USER, ...dashboard }))

const REPORTS = [
    makeReport({
        id: 'report-1',
        title: 'Signup form rejects plus-addressed emails',
        summary:
            'Sign-ups with a plus sign in the email address fail validation since the last release.\n\n## Impact\n\nNew teams that use plus addressing cannot finish signing up.',
        summary_lead: 'Sign-ups with a plus sign in the email address fail validation since the last release.',
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
        summary_lead: 'Most visitors who reach the plan table leave without starting a trial.',
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
        summary_lead: 'Token usage for the summarize tool doubled after the prompt change.',
        status: SignalReportStatus.PENDING_INPUT,
        signal_count: 3,
        updated_at: '2026-09-27T10:00:00Z',
        priority: 'P2',
        actionability: 'immediately_actionable',
        source_products: ['llm_analytics'],
    }),
    makeReport({
        id: 'report-4',
        title: 'Checkout conversion fell after the address form change',
        summary:
            'Fewer people finish checkout since the address form gained a required phone field.\n\n[Checkout conversion](chart:checkout-conversion)\n\nThe drop is sharpest on mobile, where the field is hard to fill.',
        summary_lead:
            'Fewer people finish checkout since the address form gained a required phone field. The drop is sharpest on mobile, where the field is hard to fill.',
        status: SignalReportStatus.READY,
        signal_count: 4,
        updated_at: '2026-09-28T08:00:00Z',
        priority: 'P1',
        actionability: 'immediately_actionable',
        source_products: ['product_analytics'],
        charts: [
            {
                chart_id: 'checkout-conversion',
                title: 'Checkout conversion',
                query: {
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'TrendsQuery',
                        series: [{ kind: 'EventsNode', event: 'checkout completed' }],
                        dateRange: { date_from: '2026-09-14', date_to: '2026-09-28' },
                    },
                },
            },
            {
                chart_id: 'mobile-dropoff',
                title: 'Mobile drop-off at the address form',
                query: {
                    kind: 'InsightVizNode',
                    source: {
                        kind: 'TrendsQuery',
                        series: [{ kind: 'EventsNode', event: 'address form abandoned' }],
                        dateRange: { date_from: '2026-09-14', date_to: '2026-09-28' },
                    },
                },
            },
        ],
    }),
]

function briefingItem(overrides: Partial<BriefingItemApi> & Pick<BriefingItemApi, 'key' | 'label'>): BriefingItemApi {
    return {
        title: overrides.label,
        signal: '',
        url: '/project/1/inbox',
        rank: 1,
        group: 'report',
        source: 'self_driving',
        reason: 'waiting_for_you',
        state: 'open',
        source_product: null,
        report: null,
        ...overrides,
    }
}

const PERSONAL_BRIEFING: BriefingApi = {
    id: 'briefing-1',
    local_day: '2026-09-28',
    headline: 'Five items need your attention',
    paragraphs: [
        [
            { text: 'The ', item_key: null, highlight: false },
            { text: 'signup form rejects plus-addressed emails', item_key: 'report:report-1', highlight: true },
            { text: ', and a fix is waiting for your review. ', item_key: null, highlight: false },
            { text: 'LLM costs doubled', item_key: 'report:report-3', highlight: false },
            { text: ' for the summarize tool after the prompt change.', item_key: null, highlight: false },
        ],
        [
            { text: 'Trial starts on ', item_key: null, highlight: false },
            { text: 'the growth dashboard', item_key: 'dashboard:12', highlight: false },
            { text: ' fell 18% week over week, and ', item_key: null, highlight: false },
            { text: 'the error rate alert', item_key: 'alert:5', highlight: false },
            { text: ' is firing. ', item_key: null, highlight: false },
            { text: 'Ticket #1042', item_key: 'ticket:t-1', highlight: false },
            { text: ' has 3 unread messages.', item_key: null, highlight: false },
        ],
    ],
    items: [
        briefingItem({
            key: 'report:report-1',
            label: 'Plus-addressed signups fail',
            signal: 'P1, fix ready for review',
            rank: 1,
            source_product: 'error_tracking',
            title: 'Signup form rejects plus-addressed emails',
            report: {
                priority: 'P1',
                summary:
                    'Since the release on Friday, the signup form rejects emails with a plus sign. People who try again with another address finish signup, the rest drop off at the email step.',
                pull_request_state: 'open',
                pull_request_url: 'https://github.com/example-org/web/pull/4821',
                signal_count: 23,
                updated_at: '2026-09-28T15:10:00Z',
                metrics: [
                    {
                        metric_id: 'affected-users',
                        title: 'Affected users',
                        kind: 'affected_users',
                        role: 'primary',
                        value: 52,
                        series: [12, 18, 15, 22, 31, 40, 52],
                        value_format: 'count',
                        unit: 'users',
                        query: reportMetricsFixture[0].query,
                    },
                    ...reportMetricsFixture.slice(1).map((metric) => ({
                        metric_id: metric.metric_id,
                        title: metric.title,
                        kind: metric.kind,
                        role: metric.role ?? 'supporting',
                        value: metric.value ?? 0,
                        series: metric.series ?? null,
                        value_format: metric.value_format ?? 'number',
                        unit: metric.unit ?? null,
                        query: metric.query,
                    })),
                ],
                charts: [],
            },
        }),
        briefingItem({
            key: 'report:report-3',
            label: 'Summarize tool costs doubled',
            signal: 'P2, claimed by you',
            rank: 2,
            source_product: 'llm_analytics',
            title: 'Summarize tool costs doubled after the prompt change',
            report: {
                priority: 'P2',
                summary:
                    'The summarize tool now sends the whole thread as context instead of the last ten messages. Token use per call doubled on Tuesday and has stayed there. Cost per conversation rose the same amount, while answer ratings did not change. Trimming the context back would undo the rise.',
                pull_request_state: null,
                pull_request_url: null,
                signal_count: 7,
                updated_at: '2026-09-27T09:00:00Z',
                metrics: [],
                charts: [
                    {
                        chart_id: 'summarize-tokens',
                        title: 'Tokens per summarize call',
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [{ kind: 'EventsNode', event: '$ai_generation' }],
                                dateRange: { date_from: '2026-09-14', date_to: '2026-09-28' },
                            },
                        },
                    },
                ],
            },
        }),
        briefingItem({
            key: 'dashboard:12',
            label: 'Growth overview',
            signal: 'Trial starts down 18%',
            url: '/project/1/dashboard/12',
            rank: 3,
            group: 'dashboard',
            source: 'product_analytics',
            reason: 'dashboard_you_viewed',
        }),
        briefingItem({
            key: 'alert:5',
            label: 'Error rate alert',
            signal: 'Firing since 07:10',
            url: '/project/1/insights/abc123/alerts?alert_id=5',
            rank: 4,
            group: 'dashboard',
            source: 'alerts',
            reason: 'alert_firing',
        }),
        briefingItem({
            key: 'ticket:t-1',
            label: 'Ticket #1042',
            signal: '3 unread messages',
            url: '/project/1/support/tickets/t-1',
            rank: 5,
            group: 'other',
            source: 'support',
            reason: 'assigned_ticket',
        }),
    ],
    more_reports_count: 4,
    open_reports_count: 37,
    status: 'ready',
    writer: 'agent',
    created_at: '2026-09-28T06:00:00Z',
    ready_at: '2026-09-28T06:00:21Z',
}

// Today keeps sample mode, the open pane, the sidebar width and the space feed view in local storage, which outlives
// a story. Clearing it makes each story start clean, so only the sample stories show sample reports.
// A story's `spaceFeedView` parameter is written after the clear, so it starts with that saved space feed view, the
// way a returning person sees it.
function clearTodayStorage(
    Story: () => JSX.Element,
    { parameters }: { parameters: { spaceFeedView?: Record<string, unknown> } }
): JSX.Element {
    for (const key of Object.keys(window.localStorage)) {
        if (/today|spaceFeedViewLogic/i.test(key)) {
            window.localStorage.removeItem(key)
        }
    }
    for (const [reducer, value] of Object.entries(parameters.spaceFeedView ?? {})) {
        window.localStorage.setItem(`products.tasks.spaces.spaceFeedViewLogic.${reducer}`, JSON.stringify(value))
    }
    return <Story />
}

function mockReportPage(reportId: string): ReportPageApi {
    const report = REPORTS.find((candidate) => candidate.id === reportId) ?? REPORTS[0]
    const signals = mockSignals(reportId, 6).map((signal) => {
        const firstLine = signal.content.split('\n')[0]
        return {
            signal_id: signal.signal_id,
            content: signal.content,
            source_product: signal.source_product,
            source_type: signal.source_type,
            source_id: signal.source_id,
            timestamp: signal.timestamp,
            extra: { ...signal.extra },
            headline: firstLine,
            lead: firstLine,
            meta: '',
            cited: signal.source_product === 'signals_scout' ? ('code' as const) : null,
            recording: null,
            link: null,
            preview: {
                hint: 'Show the description',
                code: [],
                block: [],
                text: signal.content,
                facts: [],
                link: null,
                link_label: null,
            },
        }
    })
    return {
        lead: report.summary_lead ?? '',
        proposal: report.suggested_prompts?.[0] ?? '',
        impact_sentence: '',
        named_pull_request: null,
        solution_names_pull_request: false,
        evidence: signals.slice(0, 3),
        source_count: signals.length,
        impact_numbers:
            report.id === 'report-1'
                ? [
                      {
                          key: 'tickets',
                          value: '4',
                          sentence: 'support tickets over 3 days.',
                          signal: signals[0],
                          values: [],
                          working: null,
                      },
                  ]
                : [],
        last_seen: null,
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
                '/api/projects/:team_id/signals/reports/for_you/': { results: REPORTS, count: 7 },
                '/api/projects/:team_id/signals/reports/:id/': (req) => [
                    200,
                    REPORTS.find((report) => report.id === req.params.id) ?? REPORTS[0],
                ],
                '/api/environments/:team_id/query/:kind/': reportMetricQueryHandler,
                '/api/projects/:team_id/today/reports/:id/page/': (req) => [200, mockReportPage(String(req.params.id))],
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [], count: 0, next: null },
                '/api/projects/:team_id/signals/reports/:id/checks/': { results: [], count: 0, next: null },
                '/api/users/@me/integrations/': { results: [] },
                '/api/users/@me/integrations/slack/linkable_workspaces/': { results: [] },
                '/api/projects/:team_id/today/briefing/': () => [404, { detail: 'Not found.' }],
                '/api/projects/:team_id/task_channels/': SPACES,
                '/api/projects/:team_id/task_channels/:id/': (req) => [
                    200,
                    SPACES.find((space) => space.id === req.params.id) ?? SPACES[0],
                ],
                '/api/users/@me/integrations/codex/': { status: 'not_connected' },
                '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
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
                    const params = new URL(request.url).searchParams
                    const channel = params.get('channel')
                    const results = channel
                        ? channel === 'space-checkout'
                            ? CANVASES
                            : []
                        : VIEW_CANVASES.filter((canvas) => canvas.kind === params.get('kind')).sort((first, second) =>
                              second.updated_at.localeCompare(first.updated_at)
                          )
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
                '/api/projects/:team_id/canvases/canvas-building/': VIEW_CANVASES[1],
                '/api/projects/:team_id/tasks/task-canvas-building/': {
                    id: 'task-canvas-building',
                    title: 'Signup funnel by country',
                    latest_run: { id: 'run-canvas-building', status: 'in_progress' },
                },
                '/api/projects/:team_id/notebooks/': { results: NOTEBOOKS, count: NOTEBOOKS.length },
                '/api/projects/:team_id/dashboards/': { results: DASHBOARDS, count: DASHBOARDS.length },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': reportMetricQueryHandler,
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

export const HomeWithPersonalBriefing: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/today/briefing/': PERSONAL_BRIEFING } })],
}

// One report was resolved and another dismissed after the briefing was written.
export const HomeWithResolvedAndDismissedItems: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/today/briefing/': {
                    ...PERSONAL_BRIEFING,
                    items: PERSONAL_BRIEFING.items.map((item) =>
                        item.key === 'report:report-3'
                            ? { ...item, state: 'dismissed' }
                            : item.key === 'report:report-1'
                              ? { ...item, state: 'done' }
                              : item
                    ),
                },
            },
        }),
    ],
}

export const HomeWithNothingForYou: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/today/briefing/': {
                    ...PERSONAL_BRIEFING,
                    headline: 'Nothing needs you right now',
                    paragraphs: [],
                    items: [],
                    more_reports_count: 0,
                    open_reports_count: 0,
                    writer: 'agent',
                },
            },
        }),
    ],
}

// While a newer briefing is written, the API returns the last ready one as `writing`.
export const HomeWhileWriting: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/today/briefing/': { ...PERSONAL_BRIEFING, status: 'writing' } },
        }),
    ],
}

export const HomeWithSampleReports: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?sample=1` },
}

export const SampleReportPage: Story = {
    parameters: { pageUrl: `${urls.todayReport('sample-pr')}?sample=1` },
}

export const HomeWithNoReports: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/signals/reports/for_you/': { results: [], count: 0 } },
        }),
    ],
}

export const HomeWhenReportsFailToLoad: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/signals/reports/for_you/': () => [500, { detail: 'Server error' }] },
        }),
    ],
}

export const ReportWithPullRequest: Story = {
    parameters: { pageUrl: urls.todayReport('report-1') },
}

export const ReportProposingItsFirstPrompt: Story = {
    parameters: { pageUrl: urls.todayReport('report-2') },
}

export const ReportWithAnImpactMetric: Story = {
    parameters: { pageUrl: urls.todayReport('report-4') },
}

export const ReportWithTicketsAndEvidenceDetail: Story = {
    parameters: { pageUrl: urls.todayReport('report-1') },
}

export const ReportThatFailsToLoad: Story = {
    parameters: { pageUrl: urls.todayReport('report-1') },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/today/reports/:id/page/': () => [500, {}] } })],
}

export const ReportInANarrowWindow: Story = {
    parameters: { pageUrl: urls.todayReport('report-1'), testOptions: { viewport: { width: 800, height: 900 } } },
}

export const SpacesPane: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
    },
}

// A hovered space row shows no buttons, so the faces keep their place.
// Its actions, New session first, are in the hover card that opens beside it.
export const SpacesPaneHoveringSpaceRow: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByLabelText('Spaces'))
        const labels = await canvas.findAllByText('checkout')
        const row = labels.find((label) => label.closest('[data-attr="today-space-row"]'))
        if (row) {
            await userEvent.hover(row)
            // The card opens in a portal outside the story's canvas.
            await within(document.body).findByText('New session')
        }
    },
}

export const SpacePage: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
}

// New session opens this page. It files into the personal space until the user picks another one.
export const NewSessionPage: Story = {
    parameters: { pageUrl: urls.taskNewSession() },
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
    parameters: { pageUrl: urls.taskSpace('space-checkout'), spaceFeedView: { view: 'list' } },
}

export const SpacePagePullRequests: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout'), spaceFeedView: { types: ['pr'] } },
}

export const SpacePageCanvases: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout'), spaceFeedView: { types: ['canvas'] } },
}

export const SpacePageCanvasesListView: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout'), spaceFeedView: { types: ['canvas'], view: 'list' } },
}

export const SpacePageFiltered: Story = {
    parameters: {
        pageUrl: urls.taskSpace('space-checkout'),
        spaceFeedView: {
            filters: { createdBy: 'anyone', sources: [], status: 'unread', pinned: 'any', environment: 'any' },
        },
    },
}

// Right-click at the target's corner, where a person would, so the menu opens beside it.
function rightClick(target: Element): void {
    const { left, top } = target.getBoundingClientRect()
    fireEvent.contextMenu(target, { clientX: left + 8, clientY: top + 8 })
}

async function sidebarRow(canvasElement: HTMLElement, label: string, rowAttr: string): Promise<Element> {
    return await waitFor(() => {
        const labels = within(canvasElement).getAllByText(label)
        const row = labels.find((element) => element.closest(`[data-attr="${rowAttr}"]`))
        if (!row) {
            throw new Error(`No "${label}" text inside a [data-attr="${rowAttr}"] row`)
        }
        return row
    })
}

// Right-clicking a session row opens the same actions as its hover card.
export const SpacesPaneSessionContextMenu: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
        const row = await sidebarRow(canvasElement, 'Add a retry to the billing webhook', 'today-recent-session')
        rightClick(row)
        await within(document.body).findByText('Open in new tab')
    },
}

// Right-clicking a space row opens its actions, New session first, like its hover card.
export const SpacesPaneSpaceContextMenu: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
        const row = await sidebarRow(canvasElement, 'checkout', 'today-space-row')
        rightClick(row)
        await within(document.body).findByText('New session')
    },
}

// With two sessions picked, right-clicking one of them offers the selection's actions instead of the row's.
export const SpacesPaneSelectedSessionsContextMenu: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todaySessionSelectionLogic.actions.setSelection({ ids: ['task-pinned', 'task-1'], anchorId: 'task-1' })
        const row = await sidebarRow(canvasElement, 'Add a retry to the billing webhook', 'today-recent-session')
        rightClick(row)
        await within(document.body).findByText('Pin 2 sessions')
    },
}

// Right-clicking a card in a space's feed opens the same actions as its "…" menu.
export const SpaceFeedCardContextMenu: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
    play: async ({ canvasElement }) => {
        const row = await sidebarRow(canvasElement, 'Add a retry to the billing webhook', 'today-space-feed-card')
        rightClick(row)
        await within(document.body).findByText('Open in new tab')
    },
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
    parameters: { pageUrl: urls.featureFlags() },
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

export const PhoneWidth: Story = {
    parameters: { testOptions: { viewport: { width: 390, height: 844 } } },
}

export const PhoneWidthMorePane: Story = {
    parameters: { testOptions: { viewport: { width: 390, height: 844 } } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByRole('button', { name: 'More' }))
    },
}

// The card opens on hover, which a static story can't hold, so these render its contents in the same frame.
const noop = (): void => {}

function HoverCardFrame({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="p-4">
            <Card size="sm" className="w-72 gap-0 border border-border py-0 shadow-[var(--shadow-md)]">
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
                        menuId: 'story-card',
                        // The author, who can hand the session off, so the card lists every action a finished session has.
                        userId: 179,
                    }
                )}
                onAction={noop}
                onSubmenuOpenChange={noop}
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
                onAction={noop}
            />
        </HoverCardFrame>
    ),
}

export const ReportHoverCard: Story = {
    render: () => (
        <HoverCardFrame>
            <TodayReportHoverCard
                preview={{
                    kind: 'report',
                    card: briefingItemReportCard(PERSONAL_BRIEFING.items[0]),
                    surface: 'sidebar',
                }}
            />
        </HoverCardFrame>
    ),
}

export const ReportHoverCardResolved: Story = {
    render: () => (
        <HoverCardFrame>
            <TodayReportHoverCard
                preview={{
                    kind: 'report',
                    card: briefingItemReportCard({ ...PERSONAL_BRIEFING.items[1], state: 'done' }),
                    surface: 'sidebar',
                }}
            />
        </HoverCardFrame>
    ),
}

// The details are picked through the logic, where the dialog saves them, so each session row shows a second line.
export const SpacesPaneWithListItemDetails: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todayListAppearanceLogic.actions.setFields(['repository', 'activity'])
    },
}

export const ListItemAppearanceDialog: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Spaces'))
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todayListAppearanceLogic.actions.setFields(['space', 'branch'])
        todayListAppearanceLogic.actions.openAppearanceDialog()
        // The dialog opens in a portal outside the story's canvas.
        await within(document.body).findByText('Edit list item appearance')
    },
}

export const ViewsAll: Story = {
    parameters: { pageUrl: urls.views() },
}

export const ViewsEmpty: Story = {
    parameters: { pageUrl: urls.views() },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/canvases/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/notebooks/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/dashboards/': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

export const ViewsNewMenu: Story = {
    parameters: { pageUrl: urls.views() },
    play: async ({ canvasElement }) => {
        const [newView] = await within(canvasElement).findAllByText('New view')
        await userEvent.click(newView)
    },
}
