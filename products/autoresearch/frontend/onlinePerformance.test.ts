import { AutoresearchRunApi, ConfusionByCutoffApi, OnlinePerformanceRowApi } from './generated/api.schemas'
import { calibrationBySegment, pooledConfusion, realizedAucSeries, validatedPredictionDates } from './onlinePerformance'

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
    const cutoff = { tp, fp, fn, tn, n_flagged: tp + fp, precision: null, recall: null }
    return { top_10: cutoff, top_20: cutoff, likely: { ...cutoff, tp: 0, fp: 0, n_flagged: 0, tn: tn + tp + fp } }
}

describe('onlinePerformance', () => {
    test('calibrationBySegment weights each bin by its people and drops empty segments', () => {
        const segments = calibrationBySegment([
            { n: 300, mean_p_y: 0.05, positive_rate: 0.04 },
            { n: 100, mean_p_y: 0.15, positive_rate: 0.2 },
            { n: 50, mean_p_y: 0.7, positive_rate: 0.6 },
        ])

        expect(
            segments.map(({ segment, people, predicted, actual }) => [segment.key, people, predicted, actual])
        ).toEqual([
            ['likely', 50, 0.7, 0.6],
            ['unlikely', 400, expect.closeTo(0.075), expect.closeTo(0.08)],
        ])
    })

    test('realizedAucSeries keeps the champion rows with an AUC, oldest date first', () => {
        const points = realizedAucSeries([
            row({ prediction_date: '2026-02-12', realized_auc: 0.82 }),
            row({ prediction_date: '2026-02-12', emitted_role: 'challenger', realized_auc: 0.7 }),
            row({ prediction_date: '2026-02-11', realized_auc: null }),
            row({ prediction_date: '2026-02-10', realized_auc: 0.79 }),
        ])

        expect(points.map((p) => [p.date, p.auc])).toEqual([
            ['2026-02-10', 0.79],
            ['2026-02-12', 0.82],
        ])
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
        expect(pooledConfusion([row({ model_id: 'new', confusion: null })], 'top_10')).toBeNull()
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
