// Run with: node --test .github/scripts/merge-queue-watch.test.mjs

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { evaluate } from './merge-queue-watch.mjs'

const NOW = new Date('2026-10-21T22:00:00Z')
const at = (minutesAgo) => new Date(NOW.getTime() - minutesAgo * 60000).toISOString()

// One Trunk result row per (PR, test run).
const rows = (run, outcome, minutesAgo, prs) =>
    prs.map((prNumber) => ({ testRunId: run, outcome, endedAt: at(minutesAgo), prNumber }))

describe('evaluate', () => {
    it('fires when one PR sits in four failed runs, and names it first', () => {
        const input = [1, 2, 3, 4].flatMap((n) => rows(`run-${n}`, 'failed', 50 - n * 10, [100, 200 + n]))
        const verdict = evaluate(input, NOW)
        assert.equal(verdict.fire, true)
        assert.deepEqual(verdict.top[0], [100, 4])
    })

    it('stays quiet below both thresholds', () => {
        const input = [1, 2, 3].flatMap((n) => rows(`run-${n}`, 'failed', n * 10, [100, 200 + n]))
        assert.equal(evaluate(input, NOW).fire, false)
    })

    it('fires on the failure rate alone when no PR repeats', () => {
        const input = Array.from({ length: 10 }, (_, n) => rows(`run-${n}`, 'failed', n + 1, [1000 + n])).flat()
        const verdict = evaluate(input, NOW)
        assert.equal(verdict.fire, true)
        assert.equal(verdict.failedLast30m, 10)
    })

    it('counts only failed runs, and skips rows without a test run id', () => {
        const input = [
            ...rows('a', 'interrupted', 5, [100]),
            ...rows('b', 'cancelled', 5, [100]),
            ...rows('c', 'passed', 5, [100]),
            { outcome: 'failed', endedAt: at(5), prNumber: 100 },
        ]
        const verdict = evaluate(input, NOW)
        assert.equal(verdict.failedRuns, 0)
        assert.equal(verdict.fire, false)
    })
})
