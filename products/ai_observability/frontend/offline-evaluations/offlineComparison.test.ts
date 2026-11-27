import type { ExperimentScoreApi } from '../generated/api.schemas'
import { aggregateDifference, comparisonIds, comparisonScoreRows } from './offlineComparison'
import { makeOfflineHistoryPoint } from './offlineScoreTrends.fixtures'

describe('offline experiment comparison', () => {
    const baseline = makeOfflineHistoryPoint(1, 0)
    const candidate = makeOfflineHistoryPoint(2, 0.25)
    const nextVersion = {
        ...candidate.summary,
        scorer: { ...candidate.summary.scorer, id: 'different-version', version: 3 },
    }

    it('aligns a shared version and keeps a partial run’s other version on its own row without an experiment score', () => {
        const rows = comparisonScoreRows([
            { experiment: baseline.experiment, summaries: [baseline.summary] },
            { experiment: candidate.experiment, summaries: [nextVersion, candidate.summary] },
        ])
        expect(rows.map((row) => [row.scorer.version, [...row.scores.keys()]])).toEqual([
            [2, [baseline.experiment.id, candidate.experiment.id]],
            [3, [candidate.experiment.id]],
        ])
    })

    it('compares numeric zero as a score and uses percentage points for a pass rate', () => {
        expect(aggregateDifference(candidate.summary, baseline.summary)).toBe('+0.25 vs. baseline')
        const scorer = { ...baseline.summary.scorer, kind: 'boolean' as const }
        expect(
            aggregateDifference(
                { ...candidate.summary, scorer, pass_rate: 0 },
                { ...baseline.summary, scorer, pass_rate: 0.25 }
            )
        ).toBe('−25 pp vs. baseline')
    })

    it('keeps disjoint experiment formulas separate even when their names and version numbers match', () => {
        const formula: ExperimentScoreApi = {
            definition_id: 'release-check',
            scorer_version_id: 'release-check-v1',
            name: 'Release check',
            version: 1,
            kind: 'boolean',
            config: {},
            inputs: [],
            status: 'ok',
            value: false,
            passed: false,
        }
        const otherFormula = { ...formula, definition_id: 'other-check', scorer_version_id: 'other-check-v1' }
        const rows = comparisonScoreRows([
            { experiment: { ...baseline.experiment, experiment_score: formula }, summaries: [] },
            { experiment: { ...candidate.experiment, experiment_score: otherFormula }, summaries: [] },
        ])
        expect(rows.map((row) => [row.id, [...row.scores.keys()]])).toEqual([
            [formula.scorer_version_id, [baseline.experiment.id]],
            [otherFormula.scorer_version_id, [candidate.experiment.id]],
        ])
    })

    it.each([
        ['a missing baseline result', undefined],
        ['different versions of the same scorer', nextVersion],
        ['no successes', makeOfflineHistoryPoint(1, null).summary],
    ] as const)('omits a difference for %s', (_, reference) => {
        expect(aggregateDifference(candidate.summary, reference)).toBeNull()
    })

    it('preserves the baseline order and rejects invalid or oversized shared links', () => {
        const ids = [2, 1, 3, 4, 5].map((index) => makeOfflineHistoryPoint(index).experiment.id)
        expect(comparisonIds([ids[0], ids[1], ids[0]].join(','))).toEqual(ids.slice(0, 2))
        expect(comparisonIds(ids.join(','))).toEqual([])
        expect(comparisonIds(`${ids[0]},invalid`)).toEqual([])
        expect(comparisonIds(ids[0])).toEqual([])
    })
})
