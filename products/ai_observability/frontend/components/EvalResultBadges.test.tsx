import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { EvaluationConfig, EvaluationRun } from '../evaluations/types'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'
import { EvalResultBadges, getEvalBadgeProps, getEvalSummaries, scopeRunsToTarget } from './EvalResultBadges'
import { getEvaluationResultDisplay, getEvaluationResultSortValue, isSentimentRun } from './EvaluationResultTag'

function makeRun(overrides: Partial<EvaluationRun> = {}): EvaluationRun {
    return {
        id: 'run-1',
        evaluation_id: 'eval-1',
        evaluation_name: 'Test Eval',
        generation_id: 'gen-1',
        trace_id: 'trace-1',
        timestamp: '2026-04-10T12:00:00Z',
        result: true,
        reasoning: '',
        status: 'completed',
        ...overrides,
    }
}

describe('EvalResultBadges', () => {
    describe('getEvalSummaries', () => {
        it('returns empty array for empty input', () => {
            expect(getEvalSummaries([])).toEqual([])
        })

        it('groups runs by evaluation_id and counts them', () => {
            const runs = [
                makeRun({ id: 'r1', evaluation_id: 'eval-a', timestamp: '2026-04-10T12:00:00Z' }),
                makeRun({ id: 'r2', evaluation_id: 'eval-a', timestamp: '2026-04-09T12:00:00Z' }),
                makeRun({ id: 'r3', evaluation_id: 'eval-b', timestamp: '2026-04-10T12:00:00Z' }),
            ]
            const summaries = getEvalSummaries(runs)
            expect(summaries).toHaveLength(2)

            const evalA = summaries.find((s) => s.latestRun.evaluation_id === 'eval-a')!
            expect(evalA.runCount).toBe(2)
            expect(evalA.latestRun.id).toBe('r1')

            const evalB = summaries.find((s) => s.latestRun.evaluation_id === 'eval-b')!
            expect(evalB.runCount).toBe(1)
        })

        it('picks the latest run regardless of input order', () => {
            const older = makeRun({ id: 'old', evaluation_id: 'eval-a', timestamp: '2026-04-01T00:00:00Z' })
            const newer = makeRun({ id: 'new', evaluation_id: 'eval-a', timestamp: '2026-04-10T00:00:00Z' })

            const ascResult = getEvalSummaries([older, newer])
            expect(ascResult[0].latestRun.id).toBe('new')

            const descResult = getEvalSummaries([newer, older])
            expect(descResult[0].latestRun.id).toBe('new')
        })

        it('handles a single run', () => {
            const summaries = getEvalSummaries([makeRun()])
            expect(summaries).toHaveLength(1)
            expect(summaries[0].runCount).toBe(1)
        })
    })

    describe('scopeRunsToTarget', () => {
        const generationRun = makeRun({ id: 'gen-run', generation_id: 'gen-1' })
        const otherGenerationRun = makeRun({ id: 'other-gen-run', generation_id: 'gen-2' })
        // HogQL returns '' (not null) for a missing $ai_target_event_id on trace-target runs.
        const traceRunEmptyString = makeRun({ id: 'trace-run-empty', generation_id: '' })
        const traceRunNull = makeRun({ id: 'trace-run-null', generation_id: null })
        const allRuns = [generationRun, otherGenerationRun, traceRunEmptyString, traceRunNull]

        it('scoped to a generation, returns only that generation runs', () => {
            expect(scopeRunsToTarget(allRuns, 'gen-1').map((r) => r.id)).toEqual(['gen-run'])
        })

        it('without a generation, returns only trace-target runs (empty string and null)', () => {
            expect(scopeRunsToTarget(allRuns).map((r) => r.id)).toEqual(['trace-run-empty', 'trace-run-null'])
        })
    })

    describe('getEvalBadgeProps', () => {
        it.each([
            ['failed status', makeRun({ status: 'failed' }), { type: 'danger', label: 'Error' }],
            ['running status', makeRun({ status: 'running' }), { type: 'primary', label: 'Running' }],
            ['null result', makeRun({ result: null }), { type: 'muted', label: 'N/A' }],
            ['true result', makeRun({ result: true }), { type: 'success', label: 'True' }],
            ['false result', makeRun({ result: false }), { type: 'danger', label: 'False' }],
            [
                'positive sentiment',
                makeRun({
                    evaluation_type: 'sentiment',
                    result: null,
                    sentiment_label: 'positive',
                    sentiment_score: 0.91,
                }),
                { type: 'success', label: 'Positive' },
            ],
            [
                'neutral sentiment',
                makeRun({
                    evaluation_type: 'sentiment',
                    result: null,
                    sentiment_label: 'neutral',
                    sentiment_score: 0.67,
                }),
                { type: 'none', label: 'Neutral' },
            ],
            [
                'negative sentiment',
                makeRun({
                    evaluation_type: 'sentiment',
                    result: null,
                    sentiment_label: 'negative',
                    sentiment_score: 0.82,
                }),
                { type: 'danger', label: 'Negative' },
            ],
            [
                'unknown sentiment',
                makeRun({ evaluation_type: 'sentiment', result: null, sentiment_label: null, sentiment_score: null }),
                { type: 'muted', label: 'Unknown' },
            ],
        ])('%s', (_name, run, expected) => {
            const props = getEvalBadgeProps(run)
            expect(props.type).toBe(expected.type)
            expect(props.label).toBe(expected.label)
            expect(props.icon).toBeTruthy()
        })

        it('prioritizes failed status over result value', () => {
            const props = getEvalBadgeProps(makeRun({ status: 'failed', result: true }))
            expect(props.label).toBe('Error')
        })

        it('prioritizes running status over result value', () => {
            const props = getEvalBadgeProps(makeRun({ status: 'running', result: true }))
            expect(props.label).toBe('Running')
        })
    })

    describe('getEvaluationResultDisplay polarity', () => {
        it('keeps the True label but marks a detector true result as danger', () => {
            const run = { status: 'completed', result: true, skipped: false } as any
            expect(getEvaluationResultDisplay(run, { trueIsFailure: true })).toMatchObject({
                type: 'danger',
                label: 'True',
            })
            expect(getEvaluationResultDisplay(run)).toMatchObject({ type: 'success', label: 'True' })
        })

        it('sorts a detector false result above its true result', () => {
            const trueRun = { status: 'completed', result: true, skipped: false } as any
            const falseRun = { status: 'completed', result: false, skipped: false } as any
            expect(getEvaluationResultSortValue(falseRun, { trueIsFailure: true })).toBeGreaterThan(
                getEvaluationResultSortValue(trueRun, { trueIsFailure: true })
            )
        })
    })

    describe('isSentimentRun', () => {
        it.each([
            ['evaluation type', makeRun({ evaluation_type: 'sentiment' })],
            ['result type', makeRun({ result_type: 'sentiment' })],
            ['sentiment label', makeRun({ sentiment_label: 'negative' })],
        ])('detects sentiment by %s', (_label, run) => {
            expect(isSentimentRun(run)).toBe(true)
        })

        it('returns false for boolean evaluation runs', () => {
            expect(isSentimentRun(makeRun())).toBe(false)
        })
    })

    describe('rendered with the trace scene evaluations logic', () => {
        const detectorEvaluation: EvaluationConfig = {
            id: 'eval-detector',
            name: 'Detects struggle',
            enabled: true,
            status: 'active',
            status_reason: null,
            status_reason_detail: null,
            evaluation_type: 'hog',
            evaluation_config: { source: 'return true' },
            output_type: 'boolean',
            output_config: { true_is_failure: true },
            conditions: [{ id: 'cond-1', rollout_percentage: 100, properties: [] }],
            target: 'trace',
            target_config: {},
            model_configuration: null,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
        }

        beforeEach(() => {
            initKeaTests()
        })

        afterEach(() => {
            cleanup()
        })

        it('colors a detector true result as danger, matching the config switch', () => {
            const evaluationsLogic = llmEvaluationsLogic()
            evaluationsLogic.mount()
            evaluationsLogic.actions.loadEvaluationsSuccess([detectorEvaluation])

            const runsLogic = generationEvaluationRunsLogic({ traceId: 'trace-1' })
            runsLogic.mount()
            runsLogic.actions.loadGenerationEvaluationRunsSuccess([
                makeRun({ evaluation_id: 'eval-detector', evaluation_name: 'Detects struggle', generation_id: '' }),
            ])

            render(
                <Provider>
                    <EvalResultBadges traceId="trace-1" />
                </Provider>
            )

            expect(screen.getByText('Detects struggle: True')).toBeInTheDocument()
            expect(document.querySelector('.LemonTag--danger')).toBeInTheDocument()
            expect(document.querySelector('.LemonTag--success')).not.toBeInTheDocument()

            evaluationsLogic.unmount()
            runsLogic.unmount()
        })
    })
})
