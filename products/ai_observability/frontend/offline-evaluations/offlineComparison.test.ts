import type { ExperimentScoreApi } from '../generated/api.schemas'
import { aggregateDifference, comparisonIds, comparisonScoreRows, experimentScoreDifference } from './offlineComparison'
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

    it('compares numeric zero without assuming a direction and treats a lower pass rate as worse for inverted booleans', () => {
        expect(aggregateDifference(candidate.summary, baseline.summary)).toEqual({ label: '+0.25', outcome: 'neutral' })
        const scorer = { ...baseline.summary.scorer, kind: 'boolean' as const, config: { true_is_failure: true } }
        expect(
            aggregateDifference(
                { ...candidate.summary, scorer, pass_rate: 0 },
                { ...baseline.summary, scorer, pass_rate: 0.25 }
            )
        ).toEqual({ label: '−25 pp worse', outcome: 'worse' })
    })

    it.each([
        ['gte', 0.75, '+0.25 better', 'better'],
        ['gte', 0.25, '−0.25 worse', 'worse'],
        ['lte', 0.75, '+0.25 worse', 'worse'],
        ['lte', 0.25, '−0.25 better', 'better'],
        ['lte', 0.5, 'Unchanged', 'neutral'],
    ] as const)(
        'uses the %s passing rule for a partially scored run with mean %s',
        (operator, mean, label, outcome) => {
            const scorer = { ...baseline.summary.scorer, config: { passing_rule: { operator, threshold: 0.8 } } }
            expect(
                aggregateDifference(
                    {
                        ...candidate.summary,
                        observed_item_count: 95,
                        status_counts: { ...candidate.summary.status_counts, ok: 3 },
                        mean,
                        scorer,
                    },
                    {
                        ...baseline.summary,
                        observed_item_count: 95,
                        status_counts: { ...baseline.summary.status_counts, ok: 95 },
                        mean: 0.5,
                        scorer,
                    }
                )
            ).toEqual({
                label,
                outcome,
            })
        }
    )

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

    it('compares categorical item pass rates, including a zero rate and an ungraded version', () => {
        const options = [
            { key: 'resolved', label: 'Resolved' },
            { key: 'review', label: 'Needs review' },
        ]
        const summary = {
            ...candidate.summary,
            scorer: {
                ...candidate.summary.scorer,
                kind: 'categorical' as const,
                config: { options, selection_mode: 'multiple' as const, passing_rule: { categories: ['resolved'] } },
            },
            mean: null,
            pass_rate: 0,
        }
        expect(aggregateDifference(summary, { ...summary, pass_rate: 0.25 })).toEqual({
            label: '−25 pp worse',
            outcome: 'worse',
        })
        const ungraded = { ...summary, scorer: { ...summary.scorer, config: { options } }, pass_rate: null }
        expect(aggregateDifference(ungraded, ungraded)).toBeNull()
    })

    it.each([
        ['gte', 0, '−0.5 worse', 'worse'],
        ['lte', 0, '−0.5 better', 'better'],
        ['gte', 0.5, 'Unchanged', 'neutral'],
    ] as const)('compares the numeric formula value using %s', (operator, value, label, outcome) => {
        const baseline = {
            ...formula,
            kind: 'numeric' as const,
            config: { passing_rule: { operator, threshold: 0.8 } },
            value: 0.5,
        }
        expect(experimentScoreDifference({ ...baseline, value }, baseline)).toEqual({ label, outcome })
    })

    it('only compares calculated scores from the same pinned formula with a passing rule', () => {
        expect(experimentScoreDifference(formula)).toBeNull()
        expect(experimentScoreDifference(formula, { ...formula, scorer_version_id: 'other' })).toBeNull()
        expect(experimentScoreDifference({ ...formula, status: 'mixed_versions' }, formula)).toBeNull()
        expect(experimentScoreDifference(formula, { ...formula, status: 'pending' })).toBeNull()
        expect(experimentScoreDifference({ ...formula, value: null }, formula)).toBeNull()
        const numeric = { ...formula, kind: 'numeric' as const, value: 0, passed: null }
        expect(experimentScoreDifference(numeric, numeric)).toBeNull()
    })

    it('uses the reported verdict for inverted booleans and categorical formulas', () => {
        const pass = { ...formula, config: { true_is_failure: true }, passed: true, value: false }
        const fail = { ...pass, passed: false, value: true }
        expect(experimentScoreDifference(pass, fail)).toEqual({ label: 'Now passes', outcome: 'better' })
        expect(experimentScoreDifference(fail, pass)).toEqual({ label: 'Now fails', outcome: 'worse' })
        const category = {
            ...formula,
            kind: 'categorical' as const,
            config: { options: [], passing_rule: { categories: ['good', 'great'] } },
            value: ['good'],
            passed: true,
        }
        expect(experimentScoreDifference(category, { ...category, value: ['great'] })).toEqual({
            label: 'Still passes',
            outcome: 'neutral',
        })
        expect(experimentScoreDifference(category, { ...category, value: ['poor'], passed: false })).toEqual({
            label: 'Now passes',
            outcome: 'better',
        })
        const ungraded = { ...category, config: { options: [] }, passed: null }
        expect(experimentScoreDifference(ungraded, ungraded)).toBeNull()
    })

    it('keeps disjoint experiment formulas separate even when their names and version numbers match', () => {
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
        const ids = Array.from({ length: 50 }, (_, index) => makeOfflineHistoryPoint(50 - index).experiment.id)
        expect(comparisonIds([...ids, ids[0]].join(','))).toEqual(ids)
        expect(comparisonIds([...ids, makeOfflineHistoryPoint(51).experiment.id].join(','))).toEqual([])
        expect(comparisonIds(`${ids[0]},invalid`)).toEqual([])
        expect(comparisonIds(ids[0])).toEqual([])
    })
})
