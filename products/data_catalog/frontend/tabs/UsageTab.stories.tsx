import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { UsageSnapshotApi } from '../generated/api.schemas'
import { UsageTab } from './UsageTab'

interface StoryProps {
    hasScan: boolean
    partlyFailed?: boolean
}

const MORE_METRICS = [
    'Activation rate',
    'Monthly revenue',
    'Failed payments',
    'Trial starts',
    'Churned teams',
    'Invites sent',
]
const MORE_TOPICS = [
    'Trial conversion',
    'Plan upgrades',
    'Team invitations',
    'Invoice questions',
    'Onboarding drop-off',
    'Churn risk',
]
const MORE_MEASURES = Array.from({ length: 11 }, (_, index) => `measure_${index + 1}`)

const SNAPSHOT: UsageSnapshotApi = {
    id: 'snapshot-1',
    status: 'done',
    error_message: '',
    window_start: '2026-10-01T06:00:00Z',
    window_end: '2026-10-29T06:00:00Z',
    judge_model: 'claude-opus-5-5',
    computed_at: '2026-10-29T07:12:00Z',
    created_at: '2026-10-29T06:00:00Z',
    payload: {
        metric_runs: [
            {
                metric_id: 'metric-1',
                direct_runs: { mcp: 40, posthog_ai: 25, slack: 10, posthog_code: 5 },
                direct_people: 12,
                scout_runs: 300,
            },
            {
                metric_id: 'metric-2',
                direct_runs: { posthog_ai: 6 },
                direct_people: 3,
                scout_runs: 0,
            },
            ...MORE_METRICS.map((_, index) => ({
                metric_id: `metric-${index + 3}`,
                direct_runs: { mcp: 5 - index },
                direct_people: 2,
                scout_runs: 0,
            })),
        ],
        adjusted_runs: [
            {
                metric_id: 'metric-2',
                read_metric_first: false,
                relation: 'serves',
                intent: 'How many teams signed up last week?',
                sql: "SELECT count() FROM events WHERE event = 'signup'",
                reasoning: 'Same event and aggregate.',
                occurred_at: '2026-10-20T12:00:00Z',
                session_id: 'session-1',
                is_scout: false,
            },
        ],
        topics: [
            {
                title: 'Weekly signups by plan',
                description: 'How many people sign up, split by plan.',
                session_count: 42,
                people: 11,
                coverage: { metric: 12, table: 5, nothing: 4 },
            },
            ...MORE_TOPICS.map((title, index) => ({
                title,
                description: '',
                session_count: 20 - index,
                people: 8 - index,
                coverage: { metric: 3, table: 2, nothing: 7 - index },
            })),
        ],
        table_sources: [
            { name: 'revenue_daily', sessions: 9, people: 7 },
            { name: 'accounts', sessions: 6, people: 4 },
        ],
        topic_sessions: { analysis: 62, lookup: 5, automation: 2, unclear: 1, unread: 0, coverage_unchecked: 0 },
        uncovered: [
            {
                fingerprint_digest: 'digest-1',
                measure: "sum(properties.amount) on events where event = 'purchase'",
                outcome: 'uncovered',
                matched_metric_id: null,
                distinct_people: 7,
                views: 3,
                complexity: 2,
                built: 64,
                sample_sql: "SELECT sum(properties.amount) FROM events WHERE event = 'purchase'",
                draft_name: 'purchase_revenue',
                draft_description: 'Total purchase amount.',
                draft_definition: "SELECT sum(properties.amount) FROM events WHERE event = 'purchase'",
            },
            {
                fingerprint_digest: 'digest-slice',
                measure: "count() on events where event = 'signup' and properties.plan = 'pro'",
                outcome: 'slice',
                matched_metric_id: 'metric-1',
                distinct_people: 6,
                views: 3,
                complexity: 2,
                built: 40,
                sample_sql: "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'",
                draft_name: null,
                draft_description: null,
                draft_definition: null,
            },
            ...MORE_MEASURES.map((name, index) => ({
                fingerprint_digest: `digest-${index + 2}`,
                measure: `count() on events where event = '${name}'`,
                outcome: 'uncovered',
                matched_metric_id: null,
                distinct_people: 5,
                views: 3,
                complexity: 2,
                built: 30 - index,
                sample_sql: `SELECT count() FROM events WHERE event = '${name}'`,
                draft_name: null,
                draft_description: null,
                draft_definition: null,
            })),
        ],
        proposed_metrics: [
            {
                name: 'purchase_revenue',
                description: 'Total purchase amount across all customers.',
                definition: "SELECT sum(properties.amount) FROM events WHERE event = 'purchase'",
                measures: 2,
                people: 14,
                views: 40,
                complexity: 2,
                built: 212,
                charts: [
                    {
                        insight_short_id: 'abc123',
                        insight_name: 'Revenue this month',
                        dashboard_id: 7,
                        dashboard_name: 'Company KPIs',
                        people: 9,
                    },
                    {
                        insight_short_id: 'def456',
                        insight_name: 'Purchases by plan',
                        dashboard_id: null,
                        dashboard_name: null,
                        people: 3,
                    },
                ],
                other_charts: 2,
                surfaces: [{ product: 'sql_editor', people: 2, runs: 9 }],
                agents: { people: 6, sessions: 11, runs: 31 },
            },
            {
                name: 'trial_starts',
                description: 'How many teams start a trial.',
                definition: "SELECT count() FROM events WHERE event = 'trial started'",
                measures: 1,
                people: 1,
                views: 40,
                complexity: 2,
                built: 3,
                charts: [],
                other_charts: 0,
                surfaces: [],
                agents: { people: 1, sessions: 1, runs: 3 },
            },
        ],
        failed_sections: [],
    },
}

const PARTLY_FAILED: UsageSnapshotApi = {
    ...SNAPSHOT,
    payload: {
        ...SNAPSHOT.payload,
        adjusted_runs: null,
        topics: null,
        topic_sessions: null,
        table_sources: null,
        failed_sections: [
            { section: 'adjusted_runs', reason: 'The judge model did not answer in time.' },
            { section: 'topics', reason: 'The embedding service refused the request.' },
        ],
    },
}

const meta: Meta<StoryProps> = {
    title: 'Data catalog/Usage tab',
    args: { hasScan: true },
    parameters: { mockDate: '2026-10-30', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
    render: ({ hasScan, partlyFailed }) => {
        const snapshot = partlyFailed ? PARTLY_FAILED : SNAPSHOT
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': {
                    results: [
                        { id: 'metric-1', name: 'signups', display_name: 'Signups' },
                        { id: 'metric-2', name: 'weekly_active_teams', display_name: 'Weekly active teams' },
                        ...MORE_METRICS.map((name, index) => ({
                            id: `metric-${index + 3}`,
                            name: name.toLowerCase().replaceAll(' ', '_'),
                            display_name: name,
                        })),
                    ],
                    next: null,
                },
                '/api/projects/:team_id/data_catalog/usage/': hasScan ? [snapshot] : [],
                '/api/projects/:team_id/data_catalog/usage/latest/': hasScan
                    ? snapshot
                    : () => [404, { detail: 'No usage scan has finished for this project yet.' }],
            },
        })
        return <UsageTab />
    },
}

export default meta
type Story = StoryObj<StoryProps>
export const WithScan: Story = {}
export const NoScanYet: Story = { args: { hasScan: false } }
export const PartlyFailed: Story = { args: { partlyFailed: true } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}
