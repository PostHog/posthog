import type { EvaluationSampleTrafficItemApi, TestHogResultItemApi } from '../../generated/api.schemas'
import type { EvaluationConfig } from '../types'
import { type PreviewRun, previewRuns, previewSummary } from './previewRuns'

const evaluation = {
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true' },
    output_type: 'boolean',
    output_config: {},
    target: 'generation',
} as EvaluationConfig

const row = (sampleId: string, input: string): EvaluationSampleTrafficItemApi => ({
    sample_id: sampleId,
    sample_type: 'generation',
    trace_id: 'trace-1',
    timestamp: '2026-11-05T10:00:00Z',
    input_preview: input,
    output_preview: '',
})

const run = (outcome: 'pass' | 'fail' | 'error' | null, detail: string | null = null): PreviewRun => ({
    id: 'a',
    title: '"Question"',
    href: null,
    timestamp: null,
    result: { outcome, value: '4.2', detail },
    drawerRow: null,
})

// `pluralize` joins the number and the word with a non-breaking space.
describe('previewRuns', () => {
    it('names a run with no text input instead of showing its id', () => {
        const runs = previewRuns([row('a', 'How do I reset my password?'), row('b', '')], null, evaluation)

        expect(runs.map((item) => item.title)).toEqual(['"How do I reset my password?"', 'No input'])
    })

    it('carries the error ahead of the reasoning as a result detail', () => {
        const result = {
            sample_id: 'a',
            result: null,
            reasoning: 'Looked fine',
            error: 'Global not found: generatoin',
            outcome: 'error',
        } as TestHogResultItemApi

        expect(previewRuns([row('a', 'Question')], { a: result }, evaluation)[0].result).toEqual({
            outcome: 'error',
            value: 'N/A',
            detail: 'Global not found: generatoin',
        })
    })

    it.each([
        ['no result yet', [{ ...run(null), result: null }], null],
        [
            'passes and fails',
            [run('pass'), run('pass'), run('fail')],
            { text: '2 of 3 pass', tone: 'success', error: null },
        ],
        ['nothing passed', [run('fail'), run('fail')], { text: '0 of 2 pass', tone: 'danger', error: null }],
        [
            'some errors beside graded runs',
            [run('pass'), run('error', 'boom')],
            { text: '1 of 1 pass, 1\u00a0error', tone: 'success', error: null },
        ],
        [
            'every run errored',
            [run('error', 'Global not found: generatoin'), run('error', 'Global not found: generatoin')],
            { text: '2\u00a0errors', tone: 'danger', error: 'Global not found: generatoin' },
        ],
        ['results no rule grades', [run(null), run(null)], { text: '2\u00a0results', tone: 'muted', error: null }],
    ] as [string, PreviewRun[], ReturnType<typeof previewSummary>][])('sums up %s', (_name, runs, expected) => {
        expect(previewSummary(runs)).toEqual(expected)
    })
})
