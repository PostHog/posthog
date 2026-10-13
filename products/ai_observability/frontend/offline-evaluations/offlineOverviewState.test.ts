jest.unmock('lib/utils/concurrencyController')

import { decodeParams, encodeParams } from 'kea-router'

import { promiseResolveReject } from 'lib/utils/async'

import {
    offlineFiltersFromUrl,
    offlineFiltersToUrl,
    offlinePreferencesKey,
    readOfflineScorerPreferences,
    saveOfflineScorerPreferences,
    withOfflineTrendReadLimit,
} from './offlineOverviewState'

const first = '11111111-1111-4111-8111-111111111111'
const second = '22222222-2222-4222-8222-222222222222'

describe('offline overview preferences', () => {
    beforeEach(() => localStorage.clear())

    it('persists chart order only in the same user and environment', () => {
        saveOfflineScorerPreferences(1, 2, [second, first])
        expect(readOfflineScorerPreferences(1, 2)).toEqual([second, first])
        expect(readOfflineScorerPreferences(2, 2)).toBeNull()
        expect(readOfflineScorerPreferences(1, 3)).toBeNull()
        saveOfflineScorerPreferences(1, 2, [])
        expect(readOfflineScorerPreferences(1, 2)).toEqual([])
    })

    it.each(['broken', '{}', '{"version":2,"scorerIds":[]}', '{"version":1,"scorerIds":["not-a-uuid"]}'])(
        'ignores malformed or unsupported stored preferences: %s',
        (raw) => {
            localStorage.setItem(offlinePreferencesKey(1, 2), raw)
            expect(readOfflineScorerPreferences(1, 2)).toBeNull()
        }
    )

    it('keeps URL input limited to supported list filters', () => {
        expect(
            offlineFiltersFromUrl({
                search: 'check',
                suite_key: 'a',
                cursor: 'old',
                limit: 500,
                scores: first,
                model_version: ['bad'],
                statuses: '',
            })
        ).toEqual({ search: 'check' })
    })

    it.each(['00123', 'true', '[draft]'])('keeps the experiment search %p in shared URLs', (search) => {
        const url = encodeParams(offlineFiltersToUrl({ search, date_from: '-7d' }), '?')
        expect(offlineFiltersFromUrl(decodeParams(url, '?'))).toEqual({ search, date_from: '-7d' })
    })

    it.each([
        [{}, { date_from: '-7d', date_to: '2026-09-28', run_source: 'ci' }],
        [
            { date_from: '-30d', date_to: '2026-09-20', run_source: 'local' },
            { date_from: '-30d', date_to: '2026-09-20', run_source: 'local' },
        ],
    ])('migrates legacy trend links without overriding shared filters: %j', (shared, expected) => {
        expect(
            offlineFiltersFromUrl({
                trend_from: '-7d',
                trend_to: '2026-09-28',
                trend_run_source: 'ci',
                trend_suite_key: 'old-suite',
                ...shared,
            })
        ).toEqual(expected)
    })
})

describe('offline trend reads', () => {
    it('limits pending reads to three, starts queued reads in order, and releases slots after errors', async () => {
        const completions = Array.from({ length: 8 }, () => promiseResolveReject<number>())
        const starts = Array.from({ length: 8 }, () => promiseResolveReject<number>())
        const started: number[] = []
        let running = 0
        let maximumRunning = 0
        const failure = new Error('Trend unavailable')
        const reads = completions.map((completion, index) =>
            withOfflineTrendReadLimit(async () => {
                started.push(index)
                starts[started.length - 1].resolve(index)
                maximumRunning = Math.max(maximumRunning, ++running)
                try {
                    return await completion.promise
                } finally {
                    running--
                }
            })
        )
        const settled = Promise.allSettled(reads)

        try {
            expect(started).toEqual([0, 1, 2])
            completions[0].reject(failure)
            expect(await starts[3].promise).toBe(3)
            for (let index = 1; index < 5; index++) {
                completions[index].resolve(index)
                expect(await starts[index + 3].promise).toBe(index + 3)
            }
            expect(maximumRunning).toBe(3)
        } finally {
            completions.forEach((completion, index) => completion.resolve(index))
            await settled
        }

        expect(await settled).toEqual([
            { status: 'rejected', reason: failure },
            ...Array.from({ length: 7 }, (_, index) => ({ status: 'fulfilled', value: index + 1 })),
        ])
        await expect(withOfflineTrendReadLimit(async () => 'next read')).resolves.toBe('next read')
    })
})
