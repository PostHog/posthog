import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type { EvaluationConfig, EvaluationReport, EvaluationReportRun } from '../types'

const EVALUATION_ID = 'eval-reports-story'

const EVALUATION: EvaluationConfig = {
    id: EVALUATION_ID,
    name: 'Answer helpfulness',
    description: '',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Is this answer helpful?' },
    output_type: 'boolean',
    output_config: { allows_na: false },
    conditions: [{ id: 'cond-1', rollout_percentage: 100, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: { provider: 'openai', model: 'gpt-5-mini', provider_key_id: null },
    total_runs: 3200,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
}

const REPORT: EvaluationReport = {
    id: 'report-story',
    evaluation: EVALUATION_ID,
    frequency: 'every_n',
    rrule: '',
    starts_at: null,
    timezone_name: 'UTC',
    next_delivery_date: null,
    delivery_targets: [{ type: 'slack', integration_id: 1, channel: 'C0001|#evals' }],
    max_sample_size: 200,
    enabled: true,
    deleted: false,
    last_delivered_at: '2026-11-10T09:00:00Z',
    report_prompt_guidance: '',
    trigger_threshold: 100,
    cooldown_minutes: 1440,
    daily_run_cap: 10,
    created_by: null,
    created_at: '2026-10-01T00:00:00Z',
}

function reportRun(
    id: string,
    periodEnd: string,
    title: string,
    passRate: number,
    previousPassRate: number,
    totalRuns: number,
    deliveryDestinations: EvaluationReportRun['delivery_destinations']
): EvaluationReportRun {
    const passed = Math.round((totalRuns * passRate) / 100)
    return {
        id,
        report: REPORT.id,
        content: {
            title,
            sections: [
                {
                    title: 'Summary',
                    content: `Pass rate moved from ${previousPassRate}% to ${passRate}% against the previous report. Most new fails are answers that skip the question's second part.`,
                },
                {
                    title: 'Answers that stop halfway',
                    content:
                        'The judge fails answers that cover the first question and ignore a follow-up in the same message.',
                },
            ],
            citations: [
                {
                    trace_id: `${id}-trace-a`,
                    reason: 'Answers the refund question and skips the follow-up about timing',
                },
                { trace_id: `${id}-trace-b`, reason: 'A passing answer to the same question, for contrast' },
            ],
            metrics: {
                output_type: 'boolean',
                total_runs: totalRuns,
                result_counts: { pass: passed, fail: totalRuns - passed },
                pass_rate: passRate,
                previous_pass_rate: previousPassRate,
                previous_total_runs: totalRuns - 40,
                period_start: periodEnd,
                period_end: periodEnd,
            },
            generation_status: 'completed',
        },
        metadata: null,
        period_start: new Date(new Date(periodEnd).getTime() - 86_400_000).toISOString(),
        period_end: periodEnd,
        delivery_status: 'delivered',
        delivery_errors: [],
        delivery_destinations: deliveryDestinations,
        created_at: periodEnd,
    }
}

const RUNS = [
    reportRun(
        'run-3',
        '2026-11-10T09:00:00.000Z',
        'Fails rose after answers started skipping follow-ups',
        81.4,
        87.6,
        1204,
        [
            { type: 'slack', name: 'evals' },
            { type: 'email', name: 'team@example.com' },
        ]
    ),
    reportRun('run-2', '2026-11-09T09:00:00.000Z', 'Pass rate steady, two tool timeouts', 87.6, 87.2, 1180, [
        { type: 'slack', name: 'evals' },
    ]),
    reportRun('run-1', '2026-11-08T09:00:00.000Z', 'First report for this evaluation', 87.2, 85.0, 960, []),
]

const scene = mswDecorator({
    get: {
        '/api/projects/:team_id/evaluations/': toPaginatedResponse([EVALUATION]),
        '/api/projects/:team_id/evaluations/:id/': EVALUATION,
        '/api/projects/:team_id/llm_analytics/evaluation_reports/': toPaginatedResponse([REPORT]),
        '/api/projects/:team_id/llm_analytics/evaluation_reports/:id/runs/': { results: RUNS, next: null },
        '/api/environments/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
        '/api/projects/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
        '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
    },
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AI observability/Evaluation reports',
    decorators: [scene],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-11',
        // The scene loads live results around the reports, so it is checked for render errors only.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta
type Story = StoryObj<{}>

export const ReportsTab: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityEvaluation(EVALUATION_ID)}?evaluation_tab=reports`,
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="llma-evaluation-report-generate"]' },
    },
}

export const ReportDrawer: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityEvaluation(EVALUATION_ID)}?evaluation_tab=reports&report_run=run-2`,
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="llma-evaluation-report-drawer"]' },
    },
}
