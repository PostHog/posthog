import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { MetricUsageApi } from '../generated/api.schemas'
import { MetricUsageTab } from './MetricUsageTab'

const USAGE: MetricUsageApi = {
    metric_id: 'metric-1',
    snapshot_id: 'snapshot-1',
    window_start: '2026-10-01T06:00:00Z',
    window_end: '2026-10-29T06:00:00Z',
    computed_at: '2026-10-29T07:12:00Z',
    runs: {
        metric_id: 'metric-1',
        direct_runs: { mcp: 40, posthog_ai: 5 },
        direct_people: 12,
        scout_runs: 300,
    },
    adjusted_runs: [
        {
            metric_id: 'metric-1',
            read_metric_first: true,
            relation: 'slice',
            intent: 'Signups from the pro plan last week',
            sql: "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'",
            reasoning: 'Same event and aggregate, with an extra plan filter.',
            occurred_at: '2026-10-20T12:00:00Z',
            session_id: 'session-1',
            is_scout: false,
        },
        {
            metric_id: 'metric-1',
            read_metric_first: false,
            relation: 'serves',
            intent: 'How many signups this month?',
            sql: "SELECT count() FROM events WHERE event = 'signup'",
            reasoning: 'Same event and aggregate.',
            occurred_at: '2026-10-22T09:30:00Z',
            session_id: 'session-2',
            is_scout: true,
        },
    ],
    failed_sections: [],
}

const PARTLY_FAILED: MetricUsageApi = {
    ...USAGE,
    adjusted_runs: [],
    failed_sections: [{ section: 'adjusted_runs', reason: 'The judge model did not answer in time.' }],
}

const meta: Meta<{ partlyFailed?: boolean }> = {
    title: 'Data catalog/Metric usage tab',
    parameters: { mockDate: '2026-10-30', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
    render: ({ partlyFailed }) => {
        useStorybookMocks({
            get: { '/api/projects/:team_id/data_catalog/metrics/signups/usage/': partlyFailed ? PARTLY_FAILED : USAGE },
        })
        return <MetricUsageTab name="signups" />
    },
}

export default meta
type Story = StoryObj<{ partlyFailed?: boolean }>
export const WithUsage: Story = {}
export const PartlyFailed: Story = { args: { partlyFailed: true } }
