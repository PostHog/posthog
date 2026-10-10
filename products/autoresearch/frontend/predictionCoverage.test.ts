import { AutoresearchPredictionCoverageApi, AutoresearchRunApi } from './generated/api.schemas'
import { coverageHistory, coverageSummary } from './predictionCoverage'

function coverage(overrides: Partial<AutoresearchPredictionCoverageApi> = {}): AutoresearchPredictionCoverageApi {
    return {
        population: 1000,
        with_score: 1000,
        never_scored: 0,
        age_days_avg: 2,
        age_days_p50: 2,
        age_days_p90: 3.5,
        age_days_max: 4.2,
        lookback_days: 30,
        ...overrides,
    }
}

function run(overrides: Partial<AutoresearchRunApi>): AutoresearchRunApi {
    return {
        id: 'run',
        pipeline: 'pipeline-1',
        run_type: 'inference',
        status: 'completed',
        rows_scored: 250,
        metrics: {},
        coverage: coverage(),
        created_at: '2026-03-01T03:00:00Z',
        ...overrides,
    } as AutoresearchRunApi
}

describe('predictionCoverage', () => {
    test.each([
        ['no run measured coverage', [run({ coverage: null })], null as Record<string, unknown> | null],
        [
            'everyone has a score',
            [run({})],
            { coveragePct: 100, measuredRescoreDays: 4, targetRescoreDays: 4, failedRunsSince: 0 },
        ],
        [
            'part of the population was never scored',
            [run({ coverage: coverage({ with_score: 600, never_scored: 400 }) })],
            { coveragePct: 60, measuredRescoreDays: null, targetRescoreDays: 4, failedRunsSince: 0 },
        ],
        [
            'scoring runs failed after the measure',
            [
                run({ status: 'failed', coverage: null, created_at: '2026-02-28T03:00:00Z' }),
                run({}),
                run({ status: 'failed', coverage: null, created_at: '2026-03-02T03:00:00Z' }),
                run({ status: 'failed', coverage: null, created_at: '2026-03-03T03:00:00Z' }),
            ],
            { coveragePct: 100, measuredRescoreDays: 4, targetRescoreDays: 4, failedRunsSince: 2 },
        ],
    ])('coverageSummary when %s', (_name, runs, expected) => {
        expect(coverageSummary(runs, 4)).toEqual(expected === null ? null : expect.objectContaining(expected))
    })

    test('coverageSummary reads the newest measured run, whatever the list order', () => {
        const summary = coverageSummary(
            [
                run({ id: 'new', coverage: coverage({ with_score: 900, never_scored: 100 }) }),
                run({ id: 'old', created_at: '2026-02-20T03:00:00Z' }),
            ],
            1
        )
        expect(summary?.coveragePct).toEqual(90)
        expect(summary?.measuredAt).toEqual('2026-03-01T03:00:00Z')
    })

    test('coverageHistory keeps the newest measured run per day, oldest day first', () => {
        const history = coverageHistory([
            run({ created_at: '2026-03-02T15:00:00Z', coverage: coverage({ with_score: 800, age_days_p50: 1 }) }),
            run({ created_at: '2026-03-01T03:00:00Z', coverage: coverage({ with_score: 500 }) }),
            run({ created_at: '2026-03-02T03:00:00Z', coverage: coverage({ with_score: 700 }) }),
            run({ created_at: '2026-03-03T03:00:00Z', status: 'failed', coverage: null }),
        ])
        expect(history).toEqual([
            { day: '2026-03-01', coveragePct: 50, ageP50Days: 2, ageP90Days: 3.5 },
            { day: '2026-03-02', coveragePct: 80, ageP50Days: 1, ageP90Days: 3.5 },
        ])
    })
})
