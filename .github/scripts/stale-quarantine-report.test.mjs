import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { classifyQuarantines, fetchQuarantined, MIN_RUNS, WINDOW_DAYS } from './stale-quarantine-report.mjs'

const now = new Date('2026-06-30T00:00:00Z')
const daysAgo = (days) => new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString()
const test = (name, quarantinedDays, metrics) => ({ name, quarantinedSince: daysAgo(quarantinedDays), metrics })

describe('stale quarantine report', () => {
    it('sorts quarantined tests by what the window proves', () => {
        const { passing, notRunning } = classifyQuarantines(
            [
                test('ran clean', 30, { runCount: MIN_RUNS, failureCount: 0 }),
                test('still failing', 30, { runCount: 100, failureCount: 1 }),
                test('too few runs', 30, { runCount: MIN_RUNS - 1, failureCount: 0 }),
                test('no runs', 40, null),
                test('zero runs', 20, { runCount: 0, failureCount: 0 }),
                test('quarantined inside the window', WINDOW_DAYS - 1, { runCount: 500, failureCount: 0 }),
                { name: 'no start date', quarantinedSince: null, metrics: { runCount: 500, failureCount: 0 } },
            ],
            now
        )
        assert.deepEqual(
            passing.map(({ test }) => test.name),
            ['ran clean']
        )
        assert.deepEqual(
            notRunning.map(({ test }) => test.name),
            ['no runs', 'zero runs']
        )
    })

    it('counts a quarantine that began exactly one window ago', () => {
        const { passing } = classifyQuarantines(
            [test('edge', WINDOW_DAYS, { runCount: MIN_RUNS, failureCount: 0 })],
            now
        )
        assert.equal(passing.length, 1)
    })

    it('follows the cursor and refuses a list it could not finish', async () => {
        const pages = [
            { data: [{ name: 'a' }], hasMore: true, nextCursor: 'c1' },
            { data: [{ name: 'b' }], hasMore: false },
        ]
        const urls = []
        const get = async (url) => {
            urls.push(new URL(url).searchParams.get('cursor'))
            return pages.shift()
        }
        assert.deepEqual(
            (await fetchQuarantined('coll', get)).map((t) => t.name),
            ['a', 'b']
        )
        assert.deepEqual(urls, [null, 'c1'])

        const endless = async () => ({ data: [], hasMore: true, nextCursor: 'x' })
        await assert.rejects(() => fetchQuarantined('coll', endless), /exceeded/)
    })
})
