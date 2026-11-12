import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel } from '~/types'

import type { EvalSuggestionApi, EvalSuggestionEstimateApi, EvalSuggestionListApi } from '../../generated/api.schemas'
import { withWidth } from '../../redesign/trace/storyFixtures'
import { EvaluationFixSuggestionBanner } from './EvaluationFixSuggestionBanner'
import { EvaluationSuggestions } from './EvaluationSuggestions'

function suggestion(overrides: Partial<EvalSuggestionApi> & Pick<EvalSuggestionApi, 'id' | 'kind'>): EvalSuggestionApi {
    return {
        status: 'proposed',
        applies: true,
        template_key: '',
        headline: '',
        outcome: '',
        reason: '',
        draft: {},
        filters: [],
        rollout_percentage: 100,
        measured_failure_rate: null,
        sample_size: null,
        evidence: [],
        estimated_weekly_runs: null,
        estimated_weekly_cost_usd: null,
        judge_model: '',
        created_evaluation: null,
        target_evaluation: null,
        target_evaluation_name: null,
        similar_evaluation: null,
        similar_evaluation_name: null,
        dismiss_reason: null,
        created_at: '2026-11-01T01:04:00Z',
        ...overrides,
    }
}

const CODE_CHECK = suggestion({
    id: 'suggestion-code',
    kind: 'new_hog',
    template_key: 'unrecovered_errors',
    headline: '1 in 80 traces ends on a failed call',
    outcome:
        'Checks every trace for a tool or model call that failed with no recovery. Free, and you see results on recent traffic right away.',
    reason: "A tool or model call failed and no later attempt succeeded. Approval pauses and cancellations don't count.",
    draft: { evaluation_type: 'hog', target: 'trace' },
    measured_failure_rate: 0.0125,
    sample_size: 400,
    evidence: [
        {
            trace_id: '7f3c2a10-0000-4000-8000-000000000001',
            reason: 'Turn ended on search_docs: TimeoutError after 30s',
        },
        { trace_id: '9b41d7e2-0000-4000-8000-000000000002', reason: 'Turn ended on the model call: 429 rate limit' },
    ],
})

const JUDGE = suggestion({
    id: 'suggestion-judge',
    kind: 'new_llm_judge',
    template_key: 'structured_output_gap',
    headline: 'Billing tickets are marked urgent 6× more often',
    outcome: 'Checks whether billing tickets marked urgent deserve it. About $0.42 a week on your AI provider key.',
    reason: 'Traces with topic = billing mark 31% of their tickets P0 or P1, while other topic values mark 5.2%.',
    draft: { evaluation_type: 'llm_judge', target: 'trace' },
    filters: [{ key: 'topic', value: ['billing'], operator: 'exact', type: 'event' }],
    rollout_percentage: 25,
    estimated_weekly_runs: 310,
    estimated_weekly_cost_usd: 0.42,
    judge_model: 'gpt-5-mini',
    evidence: [
        { trace_id: '2d8e6f04-0000-4000-8000-000000000003', reason: '2 of 3 tickets marked P0 or P1' },
        { trace_id: '5a0c9b31-0000-4000-8000-000000000004', reason: '1 of 1 tickets marked P0 or P1' },
        { trace_id: '6c1d0a42-0000-4000-8000-000000000005', reason: '3 of 5 tickets marked P0 or P1' },
    ],
})

const FIX_FILTER = suggestion({
    id: 'suggestion-fix',
    kind: 'fix_eval',
    headline: 'Your "Refund policy check" eval stopped running',
    outcome:
        'Its filter looks for app_section = support, which your traffic stopped sending. The fix changes it to app_section = help_center, so the eval runs again.',
    reason: 'It triggers on app_section = support. Your traffic now sends help_center, so the filter matches nothing.',
    draft: { conditions: [{ id: 'help-center', rollout_percentage: 100, properties: [] }] },
    target_evaluation: 'evaluation-refunds',
    target_evaluation_name: 'Refund policy check',
})

const FIX_BY_HAND = suggestion({
    id: 'suggestion-manual-fix',
    kind: 'fix_eval',
    headline: 'Your "Tone check" eval gives the same answer almost every time',
    outcome:
        'It returned true on 99% of 1200 runs in 30 days, and gives the same reasoning for both answers. Check that its prompt can tell a pass from a fail.',
    reason: 'It returned true on 99% of 1200 runs in 30 days, and gives the same reasoning for both answers.',
    target_evaluation: 'evaluation-tone',
    target_evaluation_name: 'Tone check',
})

const ESTIMATE: EvalSuggestionEstimateApi = {
    target: 'trace',
    units: 50,
    window_start: '2026-10-31T09:00:00Z',
    window_end: '2026-11-01T01:00:00Z',
    judge_model: 'gpt-5-mini',
    estimated_cost_usd: 0.07,
}

function withSuggestions(results: EvalSuggestionApi[], pending = false): Decorator[] {
    const list: EvalSuggestionListApi = {
        run: pending
            ? null
            : {
                  id: 'run-1',
                  trigger: 'scheduled',
                  created_at: '2026-11-01T01:00:00Z',
                  completed_at: '2026-11-01T01:04:00Z',
              },
        pending,
        results,
    }
    return [
        mswDecorator({
            get: {
                '/api/projects/:team_id/evaluation_suggestions/': list,
                '/api/projects/:team_id/evaluation_suggestions/:id/': ({ params }) => [
                    200,
                    results.find((item) => item.id === params.id),
                ],
                '/api/projects/:team_id/evaluation_suggestions/:id/accept_estimate/': ESTIMATE,
            },
        }),
    ]
}

const meta: Meta<typeof EvaluationSuggestions> = {
    title: 'Scenes-App/AI observability/Evaluations/Suggestions',
    component: EvaluationSuggestions,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof EvaluationSuggestions>

export const CodeCheck: Story = { decorators: withSuggestions([CODE_CHECK]) }

export const LlmJudge: Story = { decorators: withSuggestions([JUDGE]) }

export const BrokenEval: Story = { decorators: withSuggestions([FIX_FILTER, FIX_BY_HAND]) }

export const ThreeAcross: Story = {
    decorators: [withWidth(1120), ...withSuggestions([FIX_FILTER, JUDGE, CODE_CHECK])],
}

export const Narrow: Story = {
    decorators: [withWidth(520), ...withSuggestions([FIX_FILTER, JUDGE, CODE_CHECK])],
}

export const Details: Story = {
    decorators: withSuggestions([
        {
            ...JUDGE,
            similar_evaluation: 'evaluation-billing-urgency',
            similar_evaluation_name: 'Billing urgency is justified',
        },
    ]),
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Details', {}, { timeout: 5000 }))
        await within(document.body).findByText('Judge model: gpt-5-mini', {}, { timeout: 5000 })
    },
}

export const Preparing: Story = { decorators: withSuggestions([], true) }

export const NewJudgeConfirm: Story = {
    decorators: withSuggestions([JUDGE]),
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Add eval', {}, { timeout: 5000 }))
        await within(document.body).findByText('gpt-5-mini', {}, { timeout: 5000 })
    },
}

export const FixReviewBanner: Story = {
    decorators: withSuggestions([FIX_FILTER]),
    render: () => (
        <EvaluationFixSuggestionBanner
            suggestionId={FIX_FILTER.id}
            evaluationId="evaluation-refunds"
            userAccessLevel={AccessControlLevel.Editor}
            hasUnsavedChanges={false}
        />
    ),
}
