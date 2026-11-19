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
        observation: '',
        observation_scope: '',
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
        fix_problem: null,
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
    headline: 'Tool or model calls that never succeed',
    outcome: 'Flags traces where a tool or model call fails and no later attempt succeeds.',
    reason: "The agent carries on without that call's result.",
    observation: '1 of 250 sampled traces flagged',
    observation_scope: 'Sampled from the last 7 days',
    draft: {
        evaluation_type: 'hog',
        target: 'trace',
        description:
            "Fails when the last call to a tool, or the last model call, ends in an error. Each tool counts by its span name. Approval pauses and cancellations aren't errors.",
    },
    measured_failure_rate: 1 / 250,
    sample_size: 250,
    evidence: [
        {
            trace_id: '7f3c2a10-0000-4000-8000-000000000001',
            reason: 'Turn ended on search_docs: TimeoutError after 30s',
        },
    ],
})

const JUDGE = suggestion({
    id: 'suggestion-judge',
    kind: 'new_llm_judge',
    template_key: 'review',
    headline: 'Invalid line reference formats',
    outcome: 'Flags malformed references in summary bullets and notes, including ranges, lists, or placeholder text.',
    reason: 'Invalid formats can break the links readers use to jump from a summary or note into the trace.',
    observation: '9 of 27 sampled generations flagged',
    observation_scope: 'Sampled from the last day',
    draft: {
        evaluation_type: 'llm_judge',
        target: 'generation',
        description:
            'Each `summary_bullets` or `interesting_notes` entry must have a `line_refs` value that is empty or contains one line reference, such as `L45`. Ranges, lists, and placeholders fail this check.',
    },
    filters: [{ key: 'ai_feature', value: ['trace_summary'], operator: 'exact', type: 'event' }],
    rollout_percentage: 0.01,
    measured_failure_rate: 9 / 27,
    sample_size: 27,
    estimated_weekly_runs: 2804,
    estimated_weekly_cost_usd: 1.33,
    judge_model: 'gpt-5-mini',
    evidence: [
        { trace_id: '2d8e6f04-0000-4000-8000-000000000003', reason: 'line_refs is "L12-L18", a range' },
        { trace_id: '5a0c9b31-0000-4000-8000-000000000004', reason: 'line_refs is "L3, L9", a list' },
        { trace_id: '6c1d0a42-0000-4000-8000-000000000005', reason: 'line_refs is "TBD"' },
    ],
})

const FIX_FILTER = suggestion({
    id: 'suggestion-fix',
    kind: 'fix_eval',
    headline: 'A filter value no longer appears in your events',
    outcome:
        'No AI events from the last 7 days have app_section = support. The closest value sent is help_center. The fix changes the filter to that value.',
    reason: 'It has no runs in the last 30 days.',
    draft: { conditions: [{ id: 'help-center', rollout_percentage: 100, properties: [] }] },
    target_evaluation: 'evaluation-refunds',
    target_evaluation_name: 'Refund policy check',
    fix_problem: 'no_runs',
})

const NO_RECENT_EVENTS = suggestion({
    id: 'suggestion-no-events',
    kind: 'fix_eval',
    headline: 'No recent events match this eval',
    outcome:
        "No AI events from the last 7 days match this eval's filters. If you still expect traffic, check its filters.",
    reason: 'It has no runs in the last 30 days.',
    target_evaluation: 'evaluation-scout',
    target_evaluation_name: 'Support answers stay grounded',
    fix_problem: 'no_runs',
})

const PROMPT_PROBLEM = suggestion({
    id: 'suggestion-prompt',
    kind: 'fix_prompt',
    template_key: 'review',
    headline: 'Replies promise a refund date',
    outcome:
        'Flags replies that promise a date for a refund. Most sampled calls break this rule, so an eval would fail almost every call.',
    reason: "Customers plan around a date the support team can't guarantee.",
    observation: '26 of 30 sampled generations break this rule',
    observation_scope: 'Sampled from the last day',
    draft: {
        name: 'Replies promise a refund date',
        description: 'A reply must not promise a date for a refund.',
        target: 'generation',
        prompt_name: 'support-reply',
    },
    measured_failure_rate: 26 / 30,
    sample_size: 30,
    evidence: [
        { trace_id: '3e5f7a20-0000-4000-8000-000000000006', reason: 'Promised the refund by Friday' },
        { trace_id: '8d2b4c61-0000-4000-8000-000000000007', reason: 'Promised the money within 3 days' },
    ],
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

export const BrokenEval: Story = { decorators: withSuggestions([FIX_FILTER, NO_RECENT_EVENTS]) }

export const PromptProblem: Story = { decorators: withSuggestions([PROMPT_PROBLEM]) }

export const ThreeAcross: Story = {
    decorators: [withWidth(1120), ...withSuggestions([JUDGE, CODE_CHECK, NO_RECENT_EVENTS])],
}

export const Narrow: Story = {
    decorators: [withWidth(520), ...withSuggestions([JUDGE, CODE_CHECK, NO_RECENT_EVENTS])],
}

export const Details: Story = {
    decorators: withSuggestions([
        {
            ...JUDGE,
            similar_evaluation: 'evaluation-line-refs',
            similar_evaluation_name: 'Summary line references are valid',
        },
    ]),
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Details', {}, { timeout: 5000 }))
        await within(document.body).findByText('Proposed configuration', {}, { timeout: 5000 })
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
            evaluationLogicProps={{ evaluationId: 'evaluation-refunds' }}
            userAccessLevel={AccessControlLevel.Editor}
            hasUnsavedChanges={false}
        />
    ),
}
