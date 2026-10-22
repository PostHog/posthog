// Run with: node --test .github/scripts/merge-queue-watch.test.mjs

import assert from 'node:assert/strict'
import { afterEach, beforeEach, describe, it } from 'node:test'

import { analyzeTimeline, classify, evaluate, fetchResults, fetchTimelines, main } from './merge-queue-watch.mjs'

const WEBHOOK = 'https://hooks.example.com/investigate'
const SAVED_ENV = { ...process.env }

beforeEach(() => {
    Object.assign(process.env, {
        TRUNK_API_TOKEN: 'trunk-token',
        SLACK_BOT_TOKEN: 'slack-token',
        SLACK_CHANNEL: 'C1',
        INVESTIGATION_WEBHOOK_URL: WEBHOOK,
    })
})
afterEach(() => {
    process.env = { ...SAVED_ENV }
})

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
        ['six batch failures, four of them in the last hour', [150, 100, 50, 40, 30, 20], ['victim']],
        ['three failed runs', [50, 40, 30], []],
    ]) {
        it(`labels ${name} as ${expected[0] ?? 'nothing'}`, () => {
            assert.deepEqual(labelsOf(failures(100, agos)), expected)
        })
    }

    it('labels a PR likely only once a run held it alone and failed', () => {
        const input = [...failures(100, [150, 100, 50, 40, 30, 20]), ...rows('solo-100', 'failed', 10, [100])]
        assert.deepEqual(labelsOf(input), ['likely'])
    })

    it('fires on the failure rate alone when no PR repeats', () => {
        const input = Array.from({ length: 10 }, (_, n) => rows(`run-${n}`, 'failed', n + 1, [1000 + n])).flat()
        const counts = evaluate(input, NOW)
        assert.equal(counts.rateFires, true)
        assert.deepEqual(classify(counts, new Map()), [])
    })

    it('counts a run in the 30 minute rate by its end time, once however many PRs it holds', () => {
        const input = [40, 30, 20, 10].flatMap((ago) => rows(`run-${ago}`, 'failed', ago, [1, 2]))
        assert.equal(evaluate(input, NOW).failedLast30m, 3)
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
const twoCycles = () => [passedAlone(150), failedInBatch(140), passedAlone(100), failedInBatch(90)]
const failedAlone = (ago) => event('pending_failure', ago, { testRun: { testedPullRequests: [{}] } })

describe('analyzeTimeline', () => {
    for (const [name, timeline, expected] of [
        ['a pass then a batch failure, twice', twoCycles(), 2],
        ['two passes before one batch failure', [passedAlone(150), passedAlone(140), failedInBatch(130)], 1],
        ['a pass that no later failure follows', [failedInBatch(150), passedAlone(100)], 0],
        ['a failure when tested alone after a pass', [passedAlone(100), failedAlone(90)], 0],
        ['a cycle older than the long window', [passedAlone(200), failedInBatch(190)], 0],
    ]) {
        it(`counts ${expected} cycles for ${name}`, () => {
            assert.deepEqual(analyzeTimeline(timeline, NOW), { gone: false, cycles: expected })
        })
    }

    for (const state of ['merged', 'cancelled', 'failed', 'not_ready']) {
        it(`reports a PR whose latest state is ${state} as out of the queue`, () => {
            assert.equal(analyzeTimeline([...twoCycles(), event(state, 10)], NOW).gone, true)
        })
    }

    it('keeps a kicked PR that was queued again', () => {
        const timeline = [...twoCycles(), event('failed', 60), event('pending', 50)]
        assert.equal(analyzeTimeline(timeline, NOW).gone, false)
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

const noSleep = async () => {}

// A fake Trunk, Slack and webhook behind `fetch`. `calls` records every request body by endpoint.
function fakeWorld({
    alerts = [],
    webhookStatus = 200,
    resultRows = failures(100, [50, 40, 30, 20]),
    timelines = {},
    timelineStatus = 200,
} = {}) {
    const calls = []
    const json = (data, status = 200) => new Response(JSON.stringify(data), { status })
    const handler = async (url, init) => {
        const target = String(url)
        const body = init?.body ? JSON.parse(init.body) : undefined
        calls.push({ target, body })
        if (target.includes('listMergeQueueTestingResults')) {
            return json({ testingResults: resultRows, totalItems: resultRows.length })
        }
        if (target.includes('getSubmittedPullRequest')) {
            return json({ timeline: timelines[body.pr.number] ?? [] }, timelineStatus)
        }
        if (target.includes('getMergeQueueMetrics')) {
            return new Response('mq_pr_restarts_1h_total{repo="PostHog/posthog",branch="master",queue_type="main"} 3\n')
        }
        if (target.includes('conversations.history')) {
            return json({ ok: true, messages: alerts })
        }
        if (target.includes('chat.postMessage')) {
            return json({ ok: true, ts: '1.1' })
        }
        if (target.includes('chat.update')) {
            return json({ ok: true })
        }
        if (target === WEBHOOK) {
            return json({}, webhookStatus)
        }
        throw new Error(`unexpected request to ${target}`)
    }
    const to = (needle) => calls.filter((c) => c.target.includes(needle))
    return { handler, to }
}

// A quiet tick posts nothing, starts nothing, and skips the metrics read that only an alert needs.
const assertQuiet = (world) => {
    for (const needle of ['chat.postMessage', WEBHOOK, 'getMergeQueueMetrics']) {
        assert.equal(world.to(needle).length, 0, `unexpected call to ${needle}`)
    }
}

const alertMessage = (ts, keys, investigation) => ({
    ts,
    text: 'old alert',
    blocks: [],
    metadata: { event_type: 'merge_queue_loop_alert', event_payload: { keys, investigation } },
})

describe('main', () => {
    const run = (t, world) => {
        t.mock.method(globalThis, 'fetch', world.handler)
        t.mock.method(console, 'log', () => {})
        t.mock.method(console, 'warn', () => {})
        return main({ argv: ['--at', NOW.toISOString()], sleep: noSleep })
    }

    it('posts a fresh alert once, sends its ts to the webhook, and marks it started', async (t) => {
        const world = fakeWorld()
        await run(t, world)
        assert.equal(world.to('chat.postMessage').length, 1)
        const [start] = world.to(WEBHOOK)
        assert.equal(start.body.properties.ts, '1.1')
        assert.equal(start.body.properties.alert_id, 'C1:1.1')
        assert.equal(world.to('chat.update')[0].body.metadata.event_payload.investigation, 'started')
    })

    it('retries a pending investigation on the old thread without posting again', async (t) => {
        const world = fakeWorld({ alerts: [alertMessage('9.9', 'recent:100', 'pending')] })
        await run(t, world)
        assert.equal(world.to('chat.postMessage').length, 0)
        assert.equal(world.to(WEBHOOK)[0].body.properties.ts, '9.9')
    })

    it('posts nothing and starts nothing for an alert that already started', async (t) => {
        const world = fakeWorld({ alerts: [alertMessage('9.9', 'recent:100', 'started')] })
        await run(t, world)
        assertQuiet(world)
    })

    it('stays quiet when a recent alert named other PRs and no new culprit label appeared', async (t) => {
        const world = fakeWorld({ alerts: [alertMessage('9.9', 'victim:200', 'started')] })
        await run(t, world)
        assertQuiet(world)
    })

    it('alerts again inside the cooldown when a new PR is labeled a hidden culprit', async (t) => {
        const world = fakeWorld({
            alerts: [alertMessage('9.9', 'victim:200', 'started')],
            resultRows: failures(100, [160, 120, 80, 40]),
            timelines: { 100: twoCycles() },
        })
        await run(t, world)
        assert.equal(world.to('chat.postMessage').length, 1)
        assert.match(world.to('chat.postMessage')[0].body.metadata.event_payload.keys, /hidden:100/)
    })

    it('stays quiet when a PR already alerted as one culprit label now carries the other', async (t) => {
        const world = fakeWorld({
            alerts: [alertMessage('9.9', 'likely:100', 'started')],
            resultRows: failures(100, [160, 120, 80, 40]),
            timelines: { 100: twoCycles() },
        })
        await run(t, world)
        assertQuiet(world)
    })

    it('leaves a PR that left the queue out of the investigation payload', async (t) => {
        const world = fakeWorld({
            resultRows: [...failures(100, [50, 40, 30, 20]), ...failures(200, [55, 45, 35, 25])],
            timelines: { 200: [event('cancelled', 5)] },
        })
        await run(t, world)
        const [start] = world.to(WEBHOOK)
        assert.deepEqual(
            start.body.properties.top_prs.filter((p) => p.pr === 200),
            []
        )
        assert.ok(start.body.properties.top_prs.some((p) => p.pr === 100))
    })

    it('does not retry a pending investigation that belongs to an unrelated alert', async (t) => {
        const world = fakeWorld({
            alerts: [alertMessage('8.8', 'victim:200', 'pending'), alertMessage('9.9', 'recent:100', 'started')],
        })
        await run(t, world)
        assertQuiet(world)
    })

    it('still posts the alert when every timeline read fails', async (t) => {
        const world = fakeWorld({ timelineStatus: 500 })
        await run(t, world)
        assert.equal(world.to('chat.postMessage').length, 1)
    })

    it('keeps the webhook url out of the error when the request throws', async (t) => {
        process.env.INVESTIGATION_WEBHOOK_URL = 'https://secret.example.com/hook/abc'
        await assert.rejects(run(t, fakeWorld()), (err) => !err.message.includes('secret.example.com'))
    })

    it('leaves the alert posted when the webhook fails all three attempts', async (t) => {
        const world = fakeWorld({ webhookStatus: 500 })
        await assert.rejects(run(t, world), /Could not start the investigation/)
        assert.equal(world.to('chat.postMessage').length, 1)
        assert.equal(world.to(WEBHOOK).length, 3)
    })
})

describe('fetchResults', () => {
    it('reads past the first 100 row page', async (t) => {
        const all = Array.from({ length: 130 }, (_, n) => ({ testRunId: `run-${n}`, prNumber: n }))
        t.mock.method(globalThis, 'fetch', async (url, init) => {
            const { offset } = JSON.parse(init.body)
            const page = all.slice(offset, offset + 100)
            return new Response(JSON.stringify({ testingResults: page, totalItems: all.length }))
        })
        const result = await fetchResults(new Date(NOW.getTime() - 180 * 60000), NOW)
        assert.equal(result.length, 130)
    })
})

describe('fetchTimelines', () => {
    it('stops starting reads once the time budget is spent', async (t) => {
        t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ timeline: [] })))
        t.mock.method(console, 'warn', () => {})
        const clock = [0, 0, 120000]
        const now = () => clock.shift() ?? 120000
        const timelines = await fetchTimelines(
            Array.from({ length: 12 }, (_, n) => n + 1),
            now
        )
        assert.equal(timelines.size, 5)
    })
})
