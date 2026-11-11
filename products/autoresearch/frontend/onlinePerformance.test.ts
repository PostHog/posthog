import { AutoresearchRunApi, ConfusionByCutoffApi, OnlinePerformanceRowApi } from './generated/api.schemas'
import {
    accuracyStats,
    accuracyTrend,
    accuracyTrendSummary,
    calibrationByRank,
    holdoutSentence,
    liveModelRows,
    pooledConfusion,
    validatedPredictionDates,
} from './onlinePerformance'

function row(overrides: Partial<OnlinePerformanceRowApi>): OnlinePerformanceRowApi {
    return {
        prediction_date: '2026-02-10',
        emitted_role: 'champion',
        realized_auc: 0.8,
        realized_auc_ci_low: 0.75,
        realized_auc_ci_high: 0.85,
        ...overrides,
    } as OnlinePerformanceRowApi
}

function counts(tp: number, fp: number, fn: number, tn: number): ConfusionByCutoffApi {
    const cutoff = {
        tp,
        fp,
        fn,
        tn,
        n_flagged: tp + fp,
        precision: tp + fp > 0 ? tp / (tp + fp) : null,
        recall: tp + fn > 0 ? tp / (tp + fn) : null,
    }
    return {
        top_10: cutoff,
        top_20: cutoff,
        likely: { ...cutoff, tp: 0, fp: 0, n_flagged: 0, tn: tn + tp + fp, precision: null, recall: 0 },
    }
}

describe('onlinePerformance', () => {
    test('calibrationByRank pools bins by score tenth over dates and labels groups by rank, not by cut point', () => {
        const bin = (n: number, mean_p_y: number): { n: number; mean_p_y: number; positive_rate: number } => ({
            n,
            mean_p_y,
            positive_rate: mean_p_y,
        })
        const groups = calibrationByRank(
            [
                row({
                    calibration_bins: [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.3, 0.7].map((p) =>
                        bin(100, p)
                    ),
                }),
                // Tied low scores share one bin that covers the bottom five tenths.
                row({
                    prediction_date: '2026-02-11',
                    calibration_bins: [bin(500, 0.01), ...[0.05, 0.06, 0.07, 0.3, 0.7].map((p) => bin(100, p))],
                }),
            ],
            { likely_threshold: 0.6, possible_threshold: 0.2, base_rate: null }
        )

        expect(groups.map(({ label, count, predicted }) => [label, count, predicted])).toEqual([
            ['Top 10%', 200, expect.closeTo(0.7)],
            ['Next 10%', 200, expect.closeTo(0.3)],
            ['Bottom 80%', 1600, expect.closeTo(59 / 1600)],
        ])
    })

    test('accuracyTrend keeps each role on its own line, oldest date first, with gaps for missing values', () => {
        const rows = [
            row({
                prediction_date: '2026-02-12',
                model_id: 'champ',
                realized_auc: 0.82,
                confusion: counts(3, 1, 2, 94),
            }),
            row({ prediction_date: '2026-02-12', model_id: 'chal', emitted_role: 'challenger', realized_auc: 0.7 }),
            row({ prediction_date: '2026-02-11', model_id: 'champ', realized_auc: null, confusion: null }),
            row({
                prediction_date: '2026-02-10',
                model_id: 'champ',
                realized_auc: 0.79,
                confusion: counts(1, 3, 2, 94),
            }),
            row({ prediction_date: '2026-02-10', model_id: 'chal', emitted_role: 'challenger', realized_auc: 0.74 }),
        ].map((r) => ({ ...r, n_positive: 5, base_rate: 0.05 }))
        const values = (trend: ReturnType<typeof accuracyTrend>): [string, [string, number][]][] =>
            trend.series.map((s) => [s.label, s.points.map((p) => [p.date, p.value])])

        expect(values(accuracyTrend(rows, 'ranking', 'top_10', false))).toEqual([
            [
                'Champion',
                [
                    ['2026-02-10', 0.79],
                    ['2026-02-12', 0.82],
                ],
            ],
        ])
        expect(values(accuracyTrend(rows, 'ranking', 'top_10', true))[1]).toEqual([
            'Challenger',
            [
                ['2026-02-10', 0.74],
                ['2026-02-12', 0.7],
            ],
        ])
        // Likely lift is the Likely hit rate over the base rate: 3/4 against 5%.
        expect(values(accuracyTrend(rows, 'lift', 'likely', false))).toEqual([['Champion', []]])
        const likely = rows.map((r) =>
            r.confusion ? { ...r, confusion: { ...r.confusion, likely: r.confusion.top_10 } } : r
        )
        expect(values(accuracyTrend(likely, 'lift', 'likely', false))[0][1]).toEqual([
            ['2026-02-10', expect.closeTo(0.25 / 0.05)],
            ['2026-02-12', expect.closeTo(0.75 / 0.05)],
        ])
        expect(values(accuracyTrend(rows, 'calibration', 'top_10', false)).map(([label]) => label)).toEqual([
            'Champion score',
            'Actual rate',
        ])
    })

    test.each([
        {
            metric: 'hit_rate' as const,
            expected:
                'On a typical date, 30.0% of the top 10% the model flagged did “File shared”, against 4.0% of everyone.',
        },
        {
            metric: 'calibration' as const,
            expected: "Over 2 checked dates, the champion's average score stayed within 2.0 points of the actual rate.",
        },
    ])('accuracyTrendSummary describes the champion over the checked dates for $metric', ({ metric, expected }) => {
        const rows = [
            row({ prediction_date: '2026-02-12', realized_auc: 0.82, base_rate: 0.03, mean_p_y: 0.05 }),
            row({ prediction_date: '2026-02-12', emitted_role: 'challenger', realized_auc: 0.5, mean_p_y: 0.5 }),
            row({ prediction_date: '2026-02-10', realized_auc: 0.79, base_rate: 0.05, mean_p_y: 0.04 }),
        ].map((r, index) => ({
            ...r,
            n_positive: 5,
            confusion: index === 0 ? counts(4, 6, 1, 89) : counts(2, 8, 3, 87),
        }))

        expect(accuracyTrendSummary(rows, metric, 'top_10', 'File shared')).toEqual(expected)
    })

    test.each([
        {
            name: 'every date within 0.02 of holdout, the edge included',
            aucs: [0.838, 0.86],
            holdout: 0.858,
            expected:
                'In line with training. On real outcomes the model scored 0.838 to 0.860 across 2 dates, against 0.858 when it was trained.',
        },
        {
            name: 'one date further below holdout',
            aucs: [0.83, 0.86],
            holdout: 0.858,
            expected:
                'Below training. On real outcomes the model scored 0.830 to 0.860 across 2 dates, against 0.858 when it was trained.',
        },
        {
            name: 'one date',
            aucs: [0.85],
            holdout: 0.858,
            expected:
                'In line with training. On real outcomes the model scored 0.850 on Feb 10, against 0.858 when it was trained.',
        },
        {
            name: 'no holdout AUC',
            aucs: [0.83, 0.86],
            holdout: null,
            expected: 'On real outcomes the model scored 0.830 to 0.860 across 2 dates.',
        },
    ])('holdoutSentence compares realized AUC with training for $name', ({ aucs, holdout, expected }) => {
        expect(
            holdoutSentence([...aucs.map((auc) => row({ realized_auc: auc })), row({ realized_auc: null })], holdout)
        ).toEqual(expected)
    })

    test('liveModelRows keeps the live champion dates and pooledConfusion counts pre-change dates apart', () => {
        const rows = [
            row({ prediction_date: '2026-02-13', model_id: 'new', confusion: counts(3, 1, 2, 94) }),
            row({
                prediction_date: '2026-02-13',
                model_id: 'shadow',
                emitted_role: 'challenger',
                confusion: counts(9, 0, 0, 91),
            }),
            row({ prediction_date: '2026-02-12', model_id: 'new', confusion: counts(1, 3, 2, 94) }),
            row({ prediction_date: '2026-02-11', model_id: 'new', confusion: null }),
            row({ prediction_date: '2026-02-10', model_id: 'old', confusion: counts(9, 0, 0, 91) }),
            row({ prediction_date: '2026-02-09', model_id: 'new', emitted_role: 'challenger' }),
        ]
        const live = liveModelRows(rows, 'new')

        expect(live.map((r) => r.prediction_date)).toEqual(['2026-02-13', '2026-02-12', '2026-02-11'])
        expect(liveModelRows(rows, null)).toEqual(live)
        expect(liveModelRows(rows, 'promoted-today')).toEqual([])
        expect(pooledConfusion(live, 'top_10')).toEqual({
            tp: 4,
            fp: 4,
            fn: 4,
            tn: 188,
            flagged: 8,
            precision: 0.5,
            recall: 0.5,
            firstDate: '2026-02-12',
            lastDate: '2026-02-13',
            datesWithoutCounts: 1,
        })
        expect(pooledConfusion(live, 'likely')).toMatchObject({ flagged: 0, precision: null, recall: 0 })
        expect(pooledConfusion([row({ model_id: 'new', confusion: null })], 'top_10')).toBeNull()
    })

    test.each([
        {
            name: 'a checked date with outcomes',
            overrides: { lift_at_10: 3.44, mean_p_y: 0.033 },
            expected: [
                ['Strong', 'AUC 0.80, scored on Feb 10'],
                ['3.4×', 'Against everyone, scored on Feb 10'],
                ['3.0%', 'Predicted 3.3%, scored on Feb 10'],
                ['47,000', '1,410 did it, scored on Feb 10'],
            ],
        },
        {
            name: 'a near-perfect checked date',
            overrides: { realized_auc: 0.996, lift_at_10: 9.78, mean_p_y: 0.033 },
            expected: [
                ['Strong', 'AUC 0.996, scored on Feb 10'],
                ['9.8×', 'Near the maximum, scored on Feb 10'],
                ['3.0%', 'Predicted 3.3%, scored on Feb 10'],
                ['47,000', '1,410 did it, scored on Feb 10'],
            ],
        },
        {
            name: 'a checked date where no one did it',
            overrides: { realized_auc: null, lift_at_10: 0, mean_p_y: null, n_positive: 0, base_rate: 0 },
            expected: [
                ['—', 'No AUC, scored on Feb 10'],
                ['—', 'No one did it, scored on Feb 10'],
                ['0.0%', 'scored on Feb 10'],
                ['47,000', '0 did it, scored on Feb 10'],
            ],
        },
        {
            name: 'a checked date with outcomes but no lift',
            overrides: { lift_at_10: null, mean_p_y: 0.033 },
            expected: [
                ['Strong', 'AUC 0.80, scored on Feb 10'],
                ['—', 'Not measured, scored on Feb 10'],
                ['3.0%', 'Predicted 3.3%, scored on Feb 10'],
                ['47,000', '1,410 did it, scored on Feb 10'],
            ],
        },
    ])('accuracyStats names the scored date on every stat for $name', ({ overrides, expected }) => {
        const stats = accuracyStats(
            [row({ n_scored: 47000, n_positive: 1410, base_rate: 0.03, ...overrides })],
            'File shared'
        )
        expect(stats.map(({ value, detail }) => [value, detail])).toEqual(expected)
    })

    test('accuracyStats pools several dates into predictions, with lift weighted by who did it', () => {
        const stats = accuracyStats(
            [
                row({ n_scored: 1000, n_positive: 50, base_rate: 0.05, lift_at_10: 3, realized_auc: 0.82 }),
                row({ n_scored: 1000, n_positive: 30, base_rate: 0.03, lift_at_10: 2, realized_auc: 0.78 }),
            ],
            'File shared'
        )

        // pluralize() joins the count and the noun with a non-breaking space.
        expect(stats.map(({ label, value, detail }) => [label, value, detail.replace(/\s/g, ' ')])).toEqual([
            ['Ranking', 'Strong', 'AUC 0.78 to 0.82 by date'],
            ['Top 10% lift', '2.6×', '10.5% against 4.0%'],
            ['Actual rate', '4.0%', '80 of 2,000 predictions'],
            ['Predictions checked', '2,000', '2 dates, each person once a date'],
        ])
    })

    test('validatedPredictionDates counts completed validation runs that scored a model, or the champion as champion', () => {
        const scored = { per_model: { champion: { n_scored: 100 } } }
        const runs = [
            { run_type: 'validation', status: 'completed', metrics: { prediction_date: '2026-02-10', ...scored } },
            { run_type: 'validation', status: 'failed', metrics: { prediction_date: '2026-02-11', ...scored } },
            { run_type: 'validation', status: 'completed', metrics: { prediction_date: '2026-02-12', per_model: {} } },
            { run_type: 'inference', status: 'completed', metrics: { prediction_date: '2026-02-13', ...scored } },
            {
                run_type: 'validation',
                status: 'completed',
                metrics: { prediction_date: '2026-02-14', per_model: { champion: { emitted_role: 'challenger' } } },
            },
        ] as Pick<AutoresearchRunApi, 'run_type' | 'status' | 'metrics'>[]
        runs[0].metrics = { ...runs[0].metrics, per_model: { champion: { emitted_role: 'champion' } } }

        expect(validatedPredictionDates(runs)).toEqual(['2026-02-10', '2026-02-14'])
        expect(validatedPredictionDates(runs, 'champion')).toEqual(['2026-02-10'])
    })
})
