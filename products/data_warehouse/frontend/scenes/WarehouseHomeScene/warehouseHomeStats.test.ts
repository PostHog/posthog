import type { PipelineJobStatsResponseApi } from '../../generated/api.schemas'
import {
    fillRunBuckets,
    jobCountsTile,
    needsAttentionTile,
    runSuccessTile,
    successRatePercent,
} from './warehouseHomeStats'

function stats(overrides: Partial<PipelineJobStatsResponseApi> = {}): PipelineJobStatsResponseApi {
    return {
        days: 7,
        cutoff_time: '2026-11-16T10:30:00+00:00',
        total_jobs: 428,
        successful_jobs: 412,
        failed_jobs: 16,
        external_data_jobs: { total: 300, running: 2, successful: 288, failed: 12 },
        modeling_jobs: { total: 128, running: 0, successful: 124, failed: 4 },
        breakdown: {},
        ...overrides,
    }
}

describe('run stats', () => {
    it.each([
        [412, 428, 96],
        [0, 0, null],
        [1, 3, 33],
    ])('rates %s of %s runs as %s', (successful, total, expected) => {
        expect(successRatePercent(successful, total)).toBe(expected)
    })

    it('words the success tile, including the no run case', () => {
        expect(runSuccessTile(stats())).toEqual({ value: '96%', detail: '412 of 428 runs' })
        expect(runSuccessTile(stats({ total_jobs: 0, successful_jobs: 0 }))).toEqual({
            value: 'No runs',
            detail: '0 of 0 runs',
        })
    })

    it.each([
        [
            { total: 14, running: 2, successful: 0, failed: 12 },
            { value: '14', detail: '12 failed, 2 running' },
        ],
        [
            { total: 14, running: 0, successful: 14, failed: 0 },
            { value: '14', detail: 'All succeeded' },
        ],
        [
            { total: 5, running: 1, successful: 4, failed: 0 },
            { value: '5', detail: '1 running' },
        ],
        [
            { total: 0, running: 0, successful: 0, failed: 0 },
            { value: '0', detail: 'No runs' },
        ],
    ])('words a job counts tile %#', (counts, expected) => {
        expect(jobCountsTile(counts)).toEqual(expected)
    })
})

describe('fillRunBuckets', () => {
    it.each([
        [1, 24],
        [7, 7],
        [30, 30],
    ])('fills a %s day window with %s buckets, zero where the API sends none', (days, expected) => {
        const buckets = fillRunBuckets(stats({ days }))
        expect(buckets).toHaveLength(expected)
        expect(buckets.every((bucket) => bucket.successful === 0 && bucket.failed === 0)).toBe(true)
    })

    it('puts counts in their day, ignoring the day the window starts part way through', () => {
        const buckets = fillRunBuckets(
            stats({
                breakdown: {
                    '2026-11-16': { successful: 9, failed: 9 },
                    '2026-11-18': { successful: 5, failed: 1 },
                    '2026-11-23': { successful: 2, failed: 0 },
                },
            })
        )
        expect(buckets.map((bucket) => bucket.key)).toEqual([
            '2026-11-17',
            '2026-11-18',
            '2026-11-19',
            '2026-11-20',
            '2026-11-21',
            '2026-11-22',
            '2026-11-23',
        ])
        expect(buckets[1]).toMatchObject({ successful: 5, failed: 1 })
        expect(buckets[6]).toMatchObject({ successful: 2, failed: 0 })
    })

    it('keys a one day window by hour', () => {
        const buckets = fillRunBuckets(
            stats({ days: 1, breakdown: { '2026-11-16T12:00:00': { successful: 3, failed: 0 } } })
        )
        expect(buckets[0].key).toBe('2026-11-16T11')
        expect(buckets.find((bucket) => bucket.key === '2026-11-16T12')?.successful).toBe(3)
    })
})

describe('needsAttentionTile', () => {
    const issue = (status: string): any => ({ status })

    it('counts issues and flags failures', () => {
        expect(
            needsAttentionTile(
                [issue('failed'), issue('billing_limit')],
                [
                    ['failed', 1],
                    ['billing_limit', 1],
                ]
            )
        ).toEqual({
            value: '2',
            detail: '1 failed, 1 billing limit',
            danger: true,
        })
    })

    it('stays calm when nothing is wrong or nothing failed', () => {
        expect(needsAttentionTile([], [])).toEqual({ value: '0', detail: 'Nothing needs attention', danger: false })
        expect(needsAttentionTile([issue('degraded')], [['degraded', 1]]).danger).toBe(false)
    })
})
