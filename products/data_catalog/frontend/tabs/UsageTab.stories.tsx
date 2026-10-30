import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { UsageSnapshotApi } from '../generated/api.schemas'
import { UsageTab } from './UsageTab'

interface StoryProps {
    hasScan: boolean
    partlyFailed?: boolean
}

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
                source_insight_dashboard_runs: 0,
                source_insight_insight_runs: 0,
            },
            {
                metric_id: 'metric-2',
                direct_runs: { posthog_ai: 6 },
                direct_people: 3,
                scout_runs: 0,
                source_insight_dashboard_runs: 0,
                source_insight_insight_runs: 0,
            },
        ],
        adjusted_runs: [
            {
                metric_id: 'metric-2',
                fetch_outcome: 'silent',
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
                session_count: 42,
                coverage: { canonical: 18, adapted: 6, silent: 9, raw_sql_only: 7, no_sql: 2 },
                sample_intents: ['How many signups this week?', 'Signups by plan last month'],
            },
        ],
        uncovered: [
            {
                fingerprint_digest: 'digest-1',
                measure: "sum(properties.amount) on events where event = 'purchase'",
                outcome: 'uncovered',
                matched_metric_id: null,
                matched_metric_status: null,
                distinct_people: 7,
                active_days: 12,
                runs: 64,
                scout_runs: 210,
                sample_sql: "SELECT sum(properties.amount) FROM events WHERE event = 'purchase'",
                draft_name: 'purchase_revenue',
                draft_description: 'Total purchase amount.',
                draft_definition: "SELECT sum(properties.amount) FROM events WHERE event = 'purchase'",
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
