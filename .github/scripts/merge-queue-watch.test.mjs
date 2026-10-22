// Run with: node --test .github/scripts/merge-queue-watch.test.mjs

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { analyzeTimeline, classify, evaluate } from './merge-queue-watch.mjs'

const NOW = new Date('2026-10-21T22:00:00Z')
const minutesAgo = (n) => new Date(NOW.getTime() - n * 60000).toISOString()

// One Trunk result row per (PR, test run).
const rows = (run, outcome, ago, prs) =>
    prs.map((prNumber) => ({ testRunId: run, outcome, endedAt: minutesAgo(ago), prNumber }))

// A PR that fails in `agos` (minutes ago), batched with a different partner each time.
const failures = (pr, agos) => agos.flatMap((ago, i) => rows(`${pr}-${i}`, 'failed', ago, [pr, 9000 + i]))

const labelsOf = (input) =>
    classify(evaluate(input, NOW), new Map())
        .filter((f) => f.pr < 9000)
        .map((f) => f.label)

describe('count rules', () => {
    for (const [name, agos, expected] of [
        ['four failed runs in an hour', [50, 40, 30, 20], ['recent']],
        ['six failed runs spread over the long window', [170, 140, 110, 80, 50, 20], ['victim']],
        ['six failed runs, four of them in the last hour', [150, 100, 50, 40, 30, 20], ['likely']],
        ['three failed runs', [50, 40, 30], []],
    ]) {
        it(`labels ${name} as ${expected[0] ?? 'nothing'}`, () => {
            assert.deepEqual(labelsOf(failures(100, agos)), expected)
        })
    }

    it('fires on the failure rate alone when no PR repeats', () => {
        const input = Array.from({ length: 10 }, (_, n) => rows(`run-${n}`, 'failed', n + 1, [1000 + n])).flat()
        const counts = evaluate(input, NOW)
        assert.equal(counts.rateFires, true)
        assert.deepEqual(classify(counts, new Map()), [])
    })

    it('counts only failed runs, and skips rows without a test run id', () => {
        const input = [
            ...rows('a', 'interrupted', 5, [100]),
            ...rows('b', 'cancelled', 5, [100]),
            ...rows('c', 'passed', 5, [100]),
            { outcome: 'failed', endedAt: minutesAgo(5), prNumber: 100 },
        ]
        assert.equal(evaluate(input, NOW).failedRuns, 0)
    })
})

const event = (state, ago, extra = {}) => ({ state, timestamp: minutesAgo(ago), ...extra })
const passedAlone = (ago) => event('pending', ago, { pending: { reason: 'bisection_test_run_passed' } })
const failedInBatch = (ago) => event('pending_failure', ago, { testRun: { testedPullRequests: [{}, {}, {}] } })
const failedAlone = (ago) => event('pending_failure', ago, { testRun: { testedPullRequests: [{}] } })

describe('analyzeTimeline', () => {
    for (const [name, timeline, expected] of [
        [
            'a pass then a batch failure, twice',
            [passedAlone(150), failedInBatch(140), passedAlone(100), failedInBatch(90)],
            2,
        ],
        ['a pass that no later failure follows', [failedInBatch(150), passedAlone(100)], 0],
        ['a failure when tested alone after a pass', [passedAlone(100), failedAlone(90)], 0],
        ['a cycle older than the long window', [passedAlone(200), failedInBatch(190)], 0],
    ]) {
        it(`counts ${expected} cycles for ${name}`, () => {
            assert.deepEqual(analyzeTimeline(timeline, NOW), { merged: false, cycles: expected })
        })
    }

    it('reports a merged PR so the rules can skip it', () => {
        const timeline = [passedAlone(150), failedInBatch(140), passedAlone(100), failedInBatch(90), event('merged', 10)]
        assert.equal(analyzeTimeline(timeline, NOW).merged, true)
    })
})

describe('cycle rule', () => {
    it('labels a PR with two cycles and four failed runs as hidden by bisection', () => {
        const counts = evaluate(failures(100, [160, 120, 80, 40]), NOW)
        const [finding] = classify(counts, new Map([[100, 2]]))
        assert.equal(finding.label, 'hidden')
    })

    it('needs the failed-run gate, so two flakes do not read as a culprit', () => {
        const counts = evaluate(failures(100, [160, 120, 80]), NOW)
        assert.deepEqual(classify(counts, new Map([[100, 2]])), [])
    })
})
