import { AutoresearchRunApi, ConfusionByCutoffApi, OnlinePerformanceRowApi } from './generated/api.schemas'
import {
    accuracyStats,
    accuracySummary,
    accuracyTrend,
    accuracyTrendSummary,
    calibrationBySegment,
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
    test('calibrationBySegment weights each bin by its people and drops empty segments', () => {
        const segments = calibrationBySegment(
            [
                { n: 300, mean_p_y: 0.05, positive_rate: 0.04 },
                { n: 100, mean_p_y: 0.15, positive_rate: 0.2 },
                { n: 50, mean_p_y: 0.7, positive_rate: 0.6 },
            ],
            { likely_threshold: 0.6, possible_threshold: 0.2, base_rate: null }
        )

        expect(
            segments.map(({ segment, people, predicted, actual }) => [segment.key, people, predicted, actual])
        ).toEqual([
            ['likely', 50, 0.7, 0.6],
            ['unlikely', 400, expect.closeTo(0.075), expect.closeTo(0.08)],
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
            metric: 'ranking' as const,
            expected:
                'Over 2 checked dates, realized AUC ranged from 0.790 to 0.820. It matched or beat its holdout AUC of 0.800 on 1 of 2 dates.',
        },
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

        expect(accuracyTrendSummary(rows, metric, 'top_10', 'File shared', 0.8)).toEqual(expected)
    })

    test('pooledConfusion sums the current champion dates and counts pre-change dates apart', () => {
        const rows = [
            row({ prediction_date: '2026-02-13', model_id: 'new', confusion: counts(3, 1, 2, 94) }),
            row({
                prediction_date: '2026-02-13',
                model_id: 'shadow',
                emitted_role: 'shadow',
                confusion: counts(9, 0, 0, 91),
            }),
            row({ prediction_date: '2026-02-12', model_id: 'new', confusion: counts(1, 3, 2, 94) }),
            row({ prediction_date: '2026-02-11', model_id: 'new', confusion: null }),
            row({ prediction_date: '2026-02-10', model_id: 'old', confusion: counts(9, 0, 0, 91) }),
        ]

        expect(pooledConfusion(rows, 'top_10')).toEqual({
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
        expect(pooledConfusion(rows, 'likely')).toMatchObject({ flagged: 0, precision: null, recall: 0 })
        expect(accuracySummary(pooledConfusion(rows, 'top_10')!, 'top_10', 'File shared')).toEqual(
            'For people scored from Feb 12 to Feb 13, 50.0% of the top 10% the model flagged did “File shared”, against 4.0% of everyone. They include 50.0% of everyone who did it.'
        )
        expect(accuracySummary(pooledConfusion(rows, 'likely')!, 'likely', 'File shared')).toBeNull()
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
            row({ n_scored: 47000, n_positive: 1410, base_rate: 0.03, ...overrides }),
            'File shared'
        )
        expect(stats.map(({ value, detail }) => [value, detail])).toEqual(expected)
    })

    test('validatedPredictionDates counts only completed validation runs that scored a model', () => {
        const scored = { per_model: { champion: { n_scored: 100 } } }
        const runs = [
            { run_type: 'validation', status: 'completed', metrics: { prediction_date: '2026-02-10', ...scored } },
            { run_type: 'validation', status: 'failed', metrics: { prediction_date: '2026-02-11', ...scored } },
            { run_type: 'validation', status: 'completed', metrics: { prediction_date: '2026-02-12', per_model: {} } },
            { run_type: 'inference', status: 'completed', metrics: { prediction_date: '2026-02-13', ...scored } },
        ] as Pick<AutoresearchRunApi, 'run_type' | 'status' | 'metrics'>[]

        expect(validatedPredictionDates(runs)).toEqual(['2026-02-10'])
    })
})
