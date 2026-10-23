import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { ReactNode } from 'react'

import { Card } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { todayListAppearanceLogic } from '~/layout/today/todayListAppearanceLogic'
import { sessionPreview } from '~/layout/today/todayPreviewCards'
import { DEFAULT_RECENT_FILTERS } from '~/layout/today/todayRecentFilters'
import { TodaySessionHoverCard } from '~/layout/today/TodaySessionHoverCard'
import { todaySessionSelectionLogic } from '~/layout/today/todaySessionSelectionLogic'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { sessionItem } from '~/layout/today/todayWorkItems'
import { mswDecorator } from '~/mocks/browser'

import { makeReport, mockSignals } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { reportMetricQueryHandler } from 'products/signals/frontend/inbox/__mocks__/reportMetricMocks'
import { SignalReportPriority, SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { TaskListItemApi } from 'products/tasks/frontend/generated/api.schemas'
import type { ReportPageApi } from 'products/today/frontend/generated/api.schemas'
import type { HighlightsApi } from 'products/today/frontend/generated/api.schemas'

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
        user: ADA,
    },
    {
        id: 'chat-2',
        title: 'Weekly retention by plan',
        status: 'idle',
        type: 'assistant',
        updated_at: '2026-09-25T09:00:00Z',
        user: ADA,
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

const RECENTLY_VIEWED = [
    {
        id: 'fs-recent-1',
        path: 'Unfiled/Insights/Checkout funnel',
        type: 'insight',
        ref: 'abc123',
        href: '/insights/abc123',
        last_viewed_at: '2026-09-28T16:20:00Z',
        created_at: '2026-08-12T10:00:00Z',
    },
    {
        id: 'fs-recent-2',
        path: 'Unfiled/Dashboards/Growth overview',
        type: 'dashboard',
        ref: '12',
        href: '/dashboard/12',
        last_viewed_at: '2026-09-28T11:05:00Z',
        created_at: '2026-07-02T10:00:00Z',
    },
    {
        id: 'fs-recent-3',
        path: 'Unfiled/Feature flags/one-page-checkout',
        type: 'feature_flag',
        ref: '7',
        href: '/feature_flags/7',
        last_viewed_at: '2026-09-27T15:40:00Z',
        created_at: '2026-09-01T10:00:00Z',
    },
    {
        id: 'fs-recent-4',
        path: 'Unfiled/Cohorts/Power users',
        type: 'cohort',
        ref: '3',
        href: '/cohorts/3',
        last_viewed_at: '2026-09-26T09:10:00Z',
        created_at: '2026-06-20T10:00:00Z',
    },
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
    makeReport({
        id: 'report-5',
        title: 'Webhook retries pile up for one destination',
        summary: 'One webhook destination times out, so its retries fill the queue.',
        summary_lead: 'One webhook destination times out, so its retries fill the queue.',
        status: SignalReportStatus.READY,
        signal_count: 3,
        updated_at: '2026-09-27T16:00:00Z',
        priority: 'P2',
        actionability: 'immediately_actionable',
        source_products: ['error_tracking'],
    }),
    makeReport({
        id: 'report-6',
        title: 'Most new teams skip the third onboarding step',
        summary: 'The third onboarding step has the largest drop in the setup funnel.',
        summary_lead: 'The third onboarding step has the largest drop in the setup funnel.',
        status: SignalReportStatus.READY,
        signal_count: 2,
        updated_at: '2026-09-27T09:00:00Z',
        priority: 'P3',
        actionability: 'requires_human_input',
        source_products: ['product_analytics'],
    }),
    makeReport({
        id: 'report-7',
        title: 'Mobile recordings stop after the app goes to the background',
        summary: 'Recordings on mobile end when the app moves to the background and does not resume.',
        summary_lead: 'Recordings on mobile end when the app moves to the background and does not resume.',
        status: SignalReportStatus.READY,
        signal_count: 5,
        updated_at: '2026-09-26T12:00:00Z',
        priority: 'P2',
        actionability: 'immediately_actionable',
        source_products: ['session_replay'],
    }),
]

const MORE_REPORTS = (
    [
        ['Invite emails land in spam for one domain', 'P2', 'error_tracking'],
        ['Search returns no results for quoted terms', 'P3', 'session_replay'],
        ['Export to CSV times out for large tables', 'P2', 'error_tracking'],
        ['Onboarding checklist resets after a page reload', 'P3', 'session_replay'],
        ['Billing page shows the wrong currency for some teams', 'P1', 'error_tracking'],
        ['Dark mode toggle does not persist across sessions', 'P4', 'session_replay'],
        ['Webhook signatures fail after a key rotation', 'P2', 'error_tracking'],
        ['Free trial banner overlaps the navigation on small screens', 'P3', 'session_replay'],
        ['Password reset links expire before people open them', 'P2', 'product_analytics'],
        ['API rate limit errors spike during nightly syncs', 'P3', 'error_tracking'],
        ['Team invite form accepts duplicate emails', 'P4', 'product_analytics'],
        ['Chart tooltips cut off near the right edge', 'P4', 'session_replay'],
        ['Slow first load on the pricing page', 'P3', 'product_analytics'],
        ['Saved filters disappear after renaming a project', 'P2', 'error_tracking'],
    ] as [string, SignalReportPriority, string][]
).map(([title, priority, source], index) =>
    makeReport({
        id: `report-${index + 8}`,
        title,
        summary: title,
        summary_lead: title,
        status: SignalReportStatus.READY,
        signal_count: 2 + (index % 5),
        updated_at: `2026-09-${String(25 - (index % 9)).padStart(2, '0')}T10:00:00Z`,
        priority,
        actionability: 'requires_human_input',
        source_products: [source],
    })
)

const ALL_REPORTS = [...REPORTS, ...MORE_REPORTS]
const OPEN_REPORT_COUNT = 46

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
    const report = ALL_REPORTS.find((candidate) => candidate.id === reportId) ?? REPORTS[0]
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

const DAILY = (base: number, step: number): number[] =>
    Array.from({ length: 28 }, (_, day) => base + ((day * step) % 23) + (day % 7 >= 5 ? -base * 0.3 : 0))

const PERIOD_STARTS = (count: number, unit: 'day' | 'week'): string[] =>
    Array.from({ length: count }, (_, index) =>
        dayjs('2026-09-28')
            .startOf(unit)
            .subtract(count - index, unit)
            .format('YYYY-MM-DD')
    )

const KEY_METRIC_URL = (event: string): string =>
    `/insights/new#q=${encodeURIComponent(
        JSON.stringify({
            kind: 'InsightVizNode',
            source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event }] },
        })
    )}`

const HIGHLIGHTS: HighlightsApi = {
    status: 'ready',
    generated_at: '2026-09-28T18:00:00Z',
    day: '2026-09-28',
    refresh_at: '2026-09-29T00:00:00Z',
    pins: [],
    pulse: [
        {
            key: 'insight:wKu1pSx2',
            name: 'Weekly file uploads',
            value: 4210,
            unit: 'number',
            change_pct: 6.4,
            series: [3100, 3250, 3300, 3420, 3380, 3600, 3710, 3690, 3850, 3920, 3956, 4210],
            interval: 'week',
            url: '/dashboard/41',
            value_format: null,
            period_starts: PERIOD_STARTS(12, 'week'),
            reason: 'dashboard',
            dashboard_name: 'Growth',
            dashboard_id: 41,
            opened_days: 9,
            last_opened: '2026-09-27',
            previous_value: 3956,
            movers: [
                { label: 'Paid plans', value: 2610, change_pct: 9.2 },
                { label: 'Free plan', value: 1420, change_pct: 1.8 },
                { label: 'Trials', value: 180, change_pct: -4.8 },
            ],
        },
        {
            key: 'signup_event',
            name: 'Sign-ups',
            value: 1201,
            unit: 'events',
            change_pct: 18.1,
            series: DAILY(170, 7),
            interval: 'day',
            url: KEY_METRIC_URL('$signup'),
            value_format: null,
            period_starts: PERIOD_STARTS(28, 'day'),
            reason: 'key_metric',
            dashboard_name: null,
            dashboard_id: null,
            opened_days: null,
            last_opened: null,
            previous_value: 1017,
            movers: [],
        },
        {
            key: 'payment_event',
            name: 'Payments',
            value: 342,
            unit: 'events',
            change_pct: -3.1,
            series: DAILY(48, 5),
            interval: 'day',
            url: KEY_METRIC_URL('payment_succeeded'),
            value_format: null,
            period_starts: PERIOD_STARTS(28, 'day'),
            reason: 'key_metric',
            dashboard_name: null,
            dashboard_id: null,
            opened_days: null,
            last_opened: null,
            previous_value: 353,
            movers: [],
        },
        {
            key: 'activity_event',
            name: 'Active users',
            value: 18300,
            unit: 'people',
            change_pct: 1.6,
            series: DAILY(2600, 11),
            interval: 'day',
            url: KEY_METRIC_URL('$pageview'),
            value_format: null,
            period_starts: PERIOD_STARTS(28, 'day'),
            reason: 'key_metric',
            dashboard_name: null,
            dashboard_id: null,
            opened_days: null,
            last_opened: null,
            previous_value: 18012,
            movers: [],
        },
    ],
    items: [
        {
            key: 'alert:chk01:Checkout conversion',
            label: 'risk',
            title: 'Alert ‘Checkout conversion’ is firing',
            detail: 'Insight ‘Checkout funnel’',
            url: '/insights/chk01',
            series: null,
            score: 0.85,
            priority: 'P1',
            source: 'alerts',
        },
        {
            key: 'new_error:0195a0b2-0000-0000-0000-000000000001',
            label: 'risk',
            title: '214 users saw the new error ‘TypeError: Cannot read properties of null (reading ‘price’)’',
            detail: 'Since Sep 26 · 1.8% of active users · No owner',
            url: '/error_tracking/0195a0b2-0000-0000-0000-000000000001',
            series: null,
            score: 0.82,
            priority: 'P1',
            source: 'errors',
        },
        {
            key: 'home:rev01',
            label: 'risk',
            title: '‘Refunds’ increased by 39% last week',
            detail: '44 → 61',
            url: '/insights/rev01',
            series: [40, 43, 39, 45, 42, 41, 44, 61],
            score: 0.6,
            priority: 'P2',
            source: 'home',
        },
        {
            key: 'key_metric:payment_event',
            label: 'risk',
            title: '‘Payments’ decreased by 41% yesterday',
            detail: '118 yesterday · 200 on an average Sunday',
            url: null,
            series: [196, 172, 168, 181, 175, 162, 204, 190, 178, 171, 183, 169, 158, 118],
            score: 0.57,
            priority: 'P2',
            source: 'key_metrics',
        },
        {
            key: 'experiment_ended:12',
            label: 'opportunity',
            title: 'Experiment ‘Pricing page layout’ ended yesterday',
            detail: 'Read the results and decide whether to release the change',
            url: '/experiments/12',
            series: null,
            score: 0.6,
            priority: 'P3',
            source: 'experiments',
        },
        {
            key: 'assigned_quiet',
            label: 'opportunity',
            title: '2 of your issues had no events in the last 14 days',
            detail: '‘TypeError: e.map is not a function’ and 1 more',
            url: '/error_tracking',
            series: null,
            score: 0.35,
            priority: 'P4',
            source: 'errors',
        },
    ],
}

const SAVED_INSIGHTS = [
    { id: 1, short_id: 'chk01', name: 'Checkout conversion' },
    { id: 2, short_id: 'rev01', name: 'Refunds' },
    { id: 3, short_id: 'arr01', name: 'Monthly recurring revenue' },
    { id: 4, short_id: 'ret01', name: 'Week 1 retention' },
    { id: 5, short_id: 'trl01', name: 'Trial to paid' },
]

const CHECKOUT_METRIC: HighlightsApi['pulse'][number] = {
    ...HIGHLIGHTS.pulse[0],
    key: 'insight:chk01',
    name: 'Checkout conversion',
    value: 0.342,
    change_pct: 4.1,
    series: [0.31, 0.32, 0.3, 0.33, 0.32, 0.31, 0.33, 0.32, 0.33, 0.33, 0.329, 0.342],
    url: '/insights/chk01',
    value_format: { format: 'percentage_scaled', prefix: null, postfix: null, decimal_places: 1 },
    reason: 'routine',
    dashboard_name: null,
    dashboard_id: null,
    previous_value: 0.329,
    movers: [],
}

let storyPins: { key: string; name: string }[] = []
let storyComputingCalls = 0

const RETENTION_METRIC: HighlightsApi['pulse'][number] = {
    ...CHECKOUT_METRIC,
    key: 'insight:ret01',
    name: 'Week 1 retention',
    value: 0.412,
    change_pct: -1.2,
    series: [0.42, 0.41, 0.43, 0.42, 0.4, 0.41, 0.42, 0.41, 0.42, 0.42, 0.417, 0.412],
    url: '/insights/ret01',
    previous_value: 0.417,
}

const REVENUE_METRIC: HighlightsApi['pulse'][number] = {
    ...CHECKOUT_METRIC,
    key: 'insight:arr01',
    name: 'Monthly recurring revenue',
    value: 48200,
    change_pct: 3.4,
    series: [39000, 40100, 41000, 41800, 42600, 43300, 44000, 44900, 45700, 46200, 46600, 48200],
    url: '/insights/arr01',
    value_format: { format: 'numeric', prefix: '$', postfix: null, decimal_places: 0 },
    previous_value: 46600,
}

let storyLastReady: HighlightsApi | null = null

function storyHighlights(): HighlightsApi {
    if (storyComputingCalls > 0) {
        storyComputingCalls -= 1
        return storyLastReady
            ? { ...storyLastReady, status: 'computing' }
            : { ...HIGHLIGHTS, status: 'computing', generated_at: null, pulse: [], items: [] }
    }
    const offered = [CHECKOUT_METRIC, RETENTION_METRIC, REVENUE_METRIC, ...HIGHLIGHTS.pulse]
    const chosen = storyPins.flatMap((pin) => {
        const metric = offered.find((candidate) => candidate.key === pin.key)
        return metric ? [metric] : []
    })
    const suggested = HIGHLIGHTS.pulse.filter((metric) => !storyPins.some((pin) => pin.key === metric.key))
    const pins = storyPins.map((pin) => ({
        key: pin.key,
        status: chosen.some((metric) => metric.key === pin.key) ? ('ready' as const) : ('unavailable' as const),
    }))
    storyLastReady = { ...HIGHLIGHTS, pulse: [...chosen, ...suggested].slice(0, 4), pins }
    return storyLastReady
}

function keepNumbers(pins: { key: string; name: string }[]) {
    return function KeepNumbers(Story: () => JSX.Element): JSX.Element {
        storyPins = pins
        storyComputingCalls = 0
        storyLastReady = null
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
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    if (params.get('view') !== 'for_you') {
                        return [200, { results: REPORTS, count: 7 }]
                    }
                    const limit = Number(params.get('limit') ?? REPORTS.length)
                    const offset = Number(params.get('offset') ?? 0)
                    const excluded = new Set(params.get('exclude')?.split(',') ?? [])
                    const ranked = ALL_REPORTS.filter((report) => !excluded.has(report.id))
                    return [
                        200,
                        {
                            results: ranked.slice(offset, offset + limit),
                            count: OPEN_REPORT_COUNT - (ALL_REPORTS.length - ranked.length),
                        },
                    ]
                },
                '/api/projects/:team_id/signals/reports/available_reviewers/': {},
                '/api/projects/:team_id/signals/reports/:id/pr_checks/': { checks: [] },
                '/api/projects/:team_id/signals/reports/:id/pr_comments/': { comments: [] },
                '/api/projects/:team_id/signals/reports/:id/': (req) => [
                    200,
                    ALL_REPORTS.find((report) => report.id === req.params.id) ?? REPORTS[0],
                ],
                '/api/environments/:team_id/query/:kind/': reportMetricQueryHandler,
                '/api/projects/:team_id/today/reports/:id/page/': (req) => [200, mockReportPage(String(req.params.id))],
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [], count: 0, next: null },
                '/api/projects/:team_id/signals/reports/:id/checks/': { results: [], count: 0, next: null },
                '/api/projects/:team_id/signals/reports/:id/signals/': (req) => [
                    200,
                    { report: REPORTS.find((report) => report.id === req.params.id) ?? REPORTS[0], signals: [] },
                ],
                '/api/users/@me/integrations/': { results: [] },
                '/api/users/@me/integrations/slack/linkable_workspaces/': { results: [] },
                '/api/projects/:team_id/today/highlights/': () => [200, storyHighlights()],
                '/api/projects/:team_id/today/pulse_pins/': () => [200, { pins: storyPins }],
                '/api/projects/:team_id/insights/': ({ request }) => {
                    const search = (new URL(request.url).searchParams.get('search') ?? '').toLowerCase()
                    const results = SAVED_INSIGHTS.filter((insight) => insight.name.toLowerCase().includes(search))
                    return [200, { results, count: results.length, next: null, previous: null }]
                },
                '/api/projects/:team_id/task_channels/': SPACES,
                '/api/projects/:team_id/task_channels/:id/': (req) => [
                    200,
                    SPACES.find((space) => space.id === req.params.id) ?? SPACES[0],
                ],
                '/api/users/@me/integrations/codex/': { status: 'not_connected' },
                '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/projects/:team_id/sandbox_environments/': { results: [], next: null },
                '/api/projects/:team_id/sandbox_custom_images/': { results: [], next: null },
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
                    const params = new URL(request.url).searchParams
                    if (params.get('order_by') === '-last_viewed_at') {
                        return [200, { results: RECENTLY_VIEWED, count: RECENTLY_VIEWED.length }]
                    }
                    const type = params.get('type')
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
                '/api/projects/:team_id/signals/reports/:id/state/': (req) => [
                    200,
                    REPORTS.find((report) => report.id === req.params.id) ?? REPORTS[0],
                ],
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
            put: {
                '/api/projects/:team_id/today/pulse_pins/': async ({ request }) => {
                    const body = (await request.json()) as { pins: { key: string; name: string }[] }
                    storyPins = body.pins
                    storyComputingCalls = 1
                    return [200, { pins: storyPins }]
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

export const Home: Story = { decorators: [keepNumbers([])] }

export const HomeWithKeptNumbers: Story = {
    decorators: [
        keepNumbers([
            { key: 'insight:chk01', name: 'Checkout conversion' },
            { key: 'activity_event', name: 'Active users' },
        ]),
    ],
}

export const HomeWithSampleReports: Story = {
    parameters: { pageUrl: `${urls.projectHomepage()}?sample=1` },
}

export const SampleReportPage: Story = {
    parameters: { pageUrl: `${urls.todayReport('sample-pr')}?sample=1` },
}

export const HomeWithReportsOnly: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/today/highlights/': { ...HIGHLIGHTS, items: [] } },
        }),
    ],
}

export const HomeWithNoReports: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/signals/reports/': { results: [], count: 0 } },
        }),
    ],
}

export const HomeWithoutAiAndNothingNew: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [], count: 0 },
                '/api/projects/:team_id/today/highlights/': { ...HIGHLIGHTS, items: [] },
            },
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

export const HomeWithoutReportsWhenHighlightsFailToLoad: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/reports/': { results: [], count: 0 },
                '/api/projects/:team_id/today/highlights/': () => [500, { detail: 'Server error' }],
            },
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

export const ChatsPane: Story = {
    parameters: {
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS,
            FEATURE_FLAGS.PHAI_SANDBOX_MODE,
        ],
    },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Chats'))
    },
}

// Without the sandbox flag, the Chats pane starts a legacy chat instead of a task.
export const ChatsPaneOnLegacyPostHogAi: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Chats'))
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
export const ChatsPaneWithSelectedSessions: Story = {
    parameters: { pageUrl: urls.taskSpace('space-checkout') },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todaySessionSelectionLogic.actions.setSelection({ ids: ['task-pinned', 'task-1'], anchorId: 'task-1' })
    },
}

// The narrowed filters show their values in the primary color, and Clear filters shows at the end.
export const ChatsPaneWithRecentFilterMenu: Story = {
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
export const ChatsPaneChatContextMenu: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Chats'))
        const row = await sidebarRow(canvasElement, 'Add a retry to the billing webhook', 'today-recent-session')
        rightClick(row)
        await within(document.body).findByText('Open in new tab')
    },
}

// With two sessions picked, right-clicking one of them offers the selection's actions instead of the row's.
export const ChatsPaneSelectedSessionsContextMenu: Story = {
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

const PRODUCT_STARS = mswDecorator({
    get: {
        '/api/environments/:team_id/file_system_shortcut/': {
            count: 3,
            next: null,
            previous: null,
            results: [
                { id: 'star-1', path: 'Product analytics', type: 'insight', href: '/insights' },
                { id: 'star-2', path: 'Session replay', type: 'session_recording_playlist', href: '/replay/home' },
                { id: 'star-3', path: 'Error tracking', type: 'error_tracking', href: '/error_tracking' },
            ],
        },
    },
})

export const ProductsPane: Story = {
    decorators: [PRODUCT_STARS],
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Products'))
        await within(canvasElement).findByText('Starred')
    },
}

// Hovering a product row opens its card with the description, an example and the docs link.
export const ProductsPaneProductCard: Story = {
    decorators: [PRODUCT_STARS],
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Products'))
        await userEvent.hover(await sidebarRow(canvasElement, 'Web analytics', 'today-tool'))
        await within(document.body).findByText('For example')
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

export const PhoneWidthNewSessionPage: Story = {
    parameters: { pageUrl: urls.taskNewSession(), testOptions: { viewport: { width: 390, height: 844 } } },
}

export const PhoneWidthMorePane: Story = {
    parameters: { testOptions: { viewport: { width: 390, height: 844 } } },
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByRole('button', { name: 'More' }))
    },
}

// A root page: the phone header shows the title and a sidebar button, and the scene title row keeps only its actions.
export const PhoneWidthListScene: Story = {
    parameters: { pageUrl: urls.featureFlags(), testOptions: { viewport: { width: 390, height: 844 } } },
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
            />
        </HoverCardFrame>
    ),
}

// The details are picked through the logic, where the dialog saves them, so each session row shows a second line.
export const ChatsPaneWithListItemDetails: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Chats'))
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todayListAppearanceLogic.actions.setFields(['repository', 'activity'])
    },
}

export const ListItemAppearanceDialog: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Chats'))
        await within(canvasElement).findAllByText('Add a retry to the billing webhook')
        todayListAppearanceLogic.actions.setFields(['space', 'branch'])
        todayListAppearanceLogic.actions.openAppearanceDialog()
        // The dialog opens in a portal outside the story's canvas.
        await within(document.body).findByText('Edit list item appearance')
    },
}
