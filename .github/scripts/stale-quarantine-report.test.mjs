import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
    classifyQuarantines,
    fetchQuarantined,
    MIN_RUNS,
    pagesOf,
    ROWS_PER_TABLE,
    selectorOf,
    table,
    WINDOW_DAYS,
} from './stale-quarantine-report.mjs'

const now = new Date('2026-06-30T00:00:00Z')
const daysAgo = (days) => new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString()
const test = (name, quarantinedDays, metrics) => ({ name, quarantinedSince: daysAgo(quarantinedDays), metrics })

describe('stale quarantine report', () => {
    it('sorts quarantined tests by what the window proves', () => {
        const flagged = classifyQuarantines(
            [
                test('ran clean', 30, { runCount: MIN_RUNS, failureCount: 0 }),
                test('ran clean longer', 60, { runCount: MIN_RUNS, failureCount: 0 }),
                test('still failing', 30, { runCount: 100, failureCount: 1 }),
                test('too few runs', 30, { runCount: MIN_RUNS - 1, failureCount: 0 }),
                test('zero runs', 20, { runCount: 0, failureCount: 0 }),
                test('no runs', 40, null),
                test('quarantined inside the window', WINDOW_DAYS - 1, { runCount: 500, failureCount: 0 }),
                { name: 'no start date', quarantinedSince: null, metrics: { runCount: 500, failureCount: 0 } },
            ],
            now
        )
        const named = (kind) => flagged.filter((item) => item.kind === kind).map(({ test }) => test.name)
        assert.deepEqual(named('passing'), ['ran clean longer', 'ran clean'])
        assert.deepEqual(named('notRunning'), ['no runs', 'zero runs'])
    })

    it('counts a quarantine that began exactly one window ago', () => {
        const flagged = classifyQuarantines([test('edge', WINDOW_DAYS, { runCount: MIN_RUNS, failureCount: 0 })], now)
        assert.equal(flagged.length, 1)
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

    it('keeps each Slack table within 100 rows, header included, without dropping tests', () => {
        const items = Array.from({ length: ROWS_PER_TABLE * 2 + 1 }, (_, i) => ({
            test: { name: `t${i}` },
            quarantinedDays: 20,
            runs: 30,
            kind: 'passing',
            owner: 'team-devex',
        }))
        const pages = pagesOf(items)
        const tableRows = pages.map((page) => table(page).rows.length)
        assert.deepEqual(tableRows, [100, 100, 2])
        assert.equal(pages.flat().length, items.length)
    })

    it('builds an owner selector from the repo-relative path', () => {
        const selectorFor = (file) => selectorOf({ test: { file, name: 't' } }).selector
        assert.equal(selectorFor('../products/pulse/frontend/a.test.ts'), 'products/pulse/frontend/a.test.ts::t')
        assert.equal(selectorFor('./a/b.py'), 'a/b.py::t')
        assert.equal(selectorFor('posthog/api/test/test_x.py'), 'posthog/api/test/test_x.py::t')
        assert.equal(selectorFor(undefined), '::t')
    })
})
