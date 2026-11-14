import api from 'lib/api'

import { deriveVerdict, loadTraceSummaries } from './traceSummaryLoader'

describe('loadTraceSummaries', () => {
    it.each([
        ['not-a-uuid', undefined],
        ['', undefined],
        [null, undefined],
        ['0192F200000070008000000000000001', '0192f200-0000-7000-8000-000000000001'],
        ['{0192F200-0000-7000-8000-000000000001}', '0192f200-0000-7000-8000-000000000001'],
        ['urn:uuid:0192f200-0000-7000-8000-000000000001', '0192f200-0000-7000-8000-000000000001'],
    ])('normalizes evaluation target %s before metrics and navigation use it', async (target, expected) => {
        const query = jest.spyOn(api, 'queryHogQL').mockResolvedValue({
            results: [['evaluation', 'Helpfulness', true, true, '', '', target, 'trace', '', 'evaluator']],
        })
        try {
            const summaries = await loadTraceSummaries(['evaluation'], {}, '2026-01-01', '2026-01-07', 'evaluation', [])
            expect(summaries.evaluation.generationId).toBe(expected)
            expect(summaries.evaluation.evaluationVerdict).toBe('pass')
        } finally {
            query.mockRestore()
        }
    })

    it('loads verdicts for every evaluation beyond the default query page', async () => {
        const ids = Array.from({ length: 360 }, (_, i) => `evaluation-${i}`)
        const query = jest.spyOn(api, 'queryHogQL').mockImplementation(async (sql) => {
            const limit = Number(String(sql).match(/LIMIT\s+(\d+)/i)?.[1] ?? 100)
            return {
                results: ids
                    .slice(0, limit)
                    .map((id, i) => [id, 'Helpfulness', i < 320, true, '', '', '', '', '', 'evaluator']),
            }
        })
        try {
            const summaries = await loadTraceSummaries(ids, {}, '2026-01-01', '2026-01-07', 'evaluation', [])
            const verdicts = Object.values(summaries).map(({ evaluationVerdict }) => evaluationVerdict)
            expect(verdicts).toHaveLength(360)
            expect(verdicts.filter((verdict) => verdict === 'pass')).toHaveLength(320)
            expect(verdicts.filter((verdict) => verdict === 'fail')).toHaveLength(40)
        } finally {
            query.mockRestore()
        }
    })
})

describe('deriveVerdict', () => {
    it.each([
        ['true', 'false'],
        ['TRUE', 'FALSE'],
        [true, false],
    ])('reads %s as a pass and %s as a fail for a normal evaluation', (passing, failing) => {
        expect(deriveVerdict(passing, null, false)).toBe('pass')
        expect(deriveVerdict(failing, null, false)).toBe('fail')
    })

    it.each([
        ['true', 'false'],
        [true, false],
    ])('reads %s as a fail and %s as a pass for a detector', (failing, passing) => {
        expect(deriveVerdict(failing, null, true)).toBe('fail')
        expect(deriveVerdict(passing, null, true)).toBe('pass')
    })

    it.each([
        ['true', 'false', false],
        ['true', 'false', true],
        [true, false, false],
        [true, false, true],
    ])('reports %s as n/a when applicable is %s (detector: %s)', (result, applicable, trueIsFailure) => {
        expect(deriveVerdict(result, applicable, trueIsFailure)).toBe('n/a')
    })

    it('keeps a boolean true applicable from hiding the verdict', () => {
        expect(deriveVerdict(true, true, false)).toBe('pass')
    })

    it.each([false, true])('reports an unreadable result as unknown (detector: %s)', (trueIsFailure) => {
        expect(deriveVerdict(null, null, trueIsFailure)).toBe('unknown')
        expect(deriveVerdict('nonsense', null, trueIsFailure)).toBe('unknown')
    })
})
