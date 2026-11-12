import type { Meta, StoryObj } from '@storybook/react'

import type { EvaluationReportStoredMetrics } from '../types'
import { EvaluationReportMetrics } from './EvaluationReportMetrics'
import { reportHeadline } from './reportHeadline'

const meta: Meta<typeof EvaluationReportMetrics> = {
    title: 'Scenes-App/AI observability/Evaluation reports/Metrics',
    component: EvaluationReportMetrics,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj<typeof EvaluationReportMetrics>

const PERIOD = { period_start: '2026-11-09T09:00:00Z', period_end: '2026-11-10T09:00:00Z' }

function Template({ metrics }: { metrics: EvaluationReportStoredMetrics }): JSX.Element {
    const headline = reportHeadline({
        id: 'run',
        report: 'report',
        content: { title: '', sections: [], citations: [], metrics, generation_status: 'completed' },
        metadata: null,
        period_start: PERIOD.period_start,
        period_end: PERIOD.period_end,
        delivery_status: 'delivered',
        delivery_errors: [],
        delivery_destinations: [],
        created_at: PERIOD.period_end,
    })
    return (
        <div className="max-w-2xl p-4">
            <EvaluationReportMetrics metrics={metrics} headline={headline} />
        </div>
    )
}

export const PassFail: Story = {
    render: () => (
        <Template
            metrics={{
                ...PERIOD,
                output_type: 'boolean',
                total_runs: 1204,
                result_counts: { pass: 980, fail: 224 },
                pass_rate: 81.4,
                previous_pass_rate: 87.6,
                previous_total_runs: 1164,
            }}
        />
    ),
}

export const Sentiment: Story = {
    render: () => (
        <Template
            metrics={{
                ...PERIOD,
                output_type: 'sentiment',
                total_runs: 640,
                result_counts: { positive: 352, neutral: 160, negative: 128 },
                result_rates: { positive: 55, neutral: 25, negative: 20 },
                previous_result_rates: { positive: 50, neutral: 24, negative: 26 },
            }}
        />
    ),
}

export const EmptyPeriod: Story = {
    render: () => (
        <Template
            metrics={{
                ...PERIOD,
                output_type: 'boolean',
                total_runs: 0,
                result_counts: { pass: 0, fail: 0 },
                pass_rate: 0,
                previous_pass_rate: 92,
            }}
        />
    ),
}
