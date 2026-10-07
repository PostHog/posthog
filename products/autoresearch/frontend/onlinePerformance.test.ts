import { OnlinePerformanceRowApi } from './generated/api.schemas'
import { calibrationBySegment, realizedAucSeries } from './onlinePerformance'

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
})
