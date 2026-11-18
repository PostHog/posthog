const assert = require('node:assert/strict')
const { test } = require('node:test')

const notify = require('./ordered-image-alias-alerts')

const NODE = 'Build and deploy node container image'
const RUST = 'Build and deploy rust container images'
const CONTAINERS = 'Container Images CD'
const ALIAS = 'Publish ordered image alias'
const CHANNELS = 'Publish eligible shared-image channels'

function entry(id, laneResults, name = NODE, conclusion = 'success') {
    return {
        run: {
            id,
            name,
            conclusion,
            workflow_id: 17,
            run_attempt: 1,
            updated_at: new Date(id * 1000).toISOString(),
            html_url: `https://example.com/runs/${id}`,
        },
        jobs: Object.entries(laneResults).map(([jobName, jobConclusion]) => ({
            name: jobName,
            conclusion: jobConclusion,
        })),
    }
}

function nodeRun(id, aliasResult, runConclusion) {
    return entry(id, aliasResult ? { [ALIAS]: aliasResult } : {}, NODE, runConclusion)
}

function failingHistory(count) {
    return Array.from({ length: count }, (_, i) => nodeRun(100 - i, 'failure'))
}

function fakeHistory(entries) {
    const calls = []
    const runs = entries.map(({ run }) => run).sort((a, b) => b.id - a.id)
    const jobs = new Map(entries.map(({ run, jobs }) => [run.id, jobs]))
    const github = {
        rest: {
            actions: {
                async listJobsForWorkflowRun({ run_id }) {
                    calls.push(run_id)
                    assert.ok(jobs.has(run_id))
                    return { data: { jobs: jobs.get(run_id) } }
                },
                async listWorkflowRuns(params) {
                    calls.push('list runs')
                    assert.equal(params.workflow_id, 17)
                    assert.equal(params.branch, 'master')
                    assert.equal(params.event, 'push')
                    assert.equal(params.status, 'completed')
                    return {
                        data: { total_count: runs.length, workflow_runs: runs.slice(0, params.per_page) },
                    }
                },
            },
        },
    }
    return {
        calls,
        async process(run) {
            const messages = []
            await notify(
                { context: { repo: { owner: 'example', repo: 'images' }, payload: { workflow_run: run } }, github },
                {
                    token: 'example-token',
                    async fetch(url, params) {
                        assert.equal(url, 'https://slack.com/api/chat.postMessage')
                        assert.equal(params.method, 'POST')
                        const { channel, text } = JSON.parse(params.body)
                        assert.equal(channel, 'C0B11J29GP9')
                        messages.push(text)
                        return { ok: true, json: async () => ({ ok: true }) }
                    },
                }
            )
            return messages
        },
    }
}

function messagesFor(trigger, older) {
    return fakeHistory([trigger, ...older]).process(trigger.run)
}

for (const count of [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 23]) {
    test(`posts only at the thresholds for a streak of ${count}`, async () => {
        const [trigger, ...history] = failingHistory(count)
        history.push(nodeRun(100 - count, 'success'))

        const messages = await messagesFor(trigger, history)

        if ([3, 13, 23].includes(count)) {
            assert.equal(messages.length, 1)
            assert.match(messages[0], new RegExp(`failed in ${count} consecutive runs`))
            assert.ok(messages[0].includes('<https://example.com/runs/100|newest failure>'))
            assert.ok(messages[0].includes(`<https://example.com/runs/${101 - count}|first failure>`))
            assert.match(messages[0], /Kargo creates no Freight/)
        } else {
            assert.deepEqual(messages, [])
        }
    })
}

for (const count of [2, 3, 4]) {
    test(`evaluates recovery after ${count} failures`, async () => {
        const messages = await messagesFor(nodeRun(101, 'success'), failingHistory(count))
        assert.deepEqual(
            messages,
            count < 3 ? [] : ['Node.js (Build and deploy node container image) recovered in <https://example.com/runs/101|this run>.']
        )
    })
}

test('ignores skipped, cancelled and absent jobs between failures', async () => {
    const messages = await messagesFor(nodeRun(110, 'failure'), [
        nodeRun(109, 'skipped'),
        nodeRun(108, 'failure'),
        nodeRun(107, 'failure', 'cancelled'),
        nodeRun(106, 'cancelled'),
        nodeRun(105, null),
        nodeRun(104, 'failure'),
        nodeRun(103, 'success'),
    ])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /3 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/104|first failure>'))
})

test('tracks one independent lane for each Rust registry', async () => {
    const run = (id, ecr, ghcr) =>
        entry(id, { 'publish ordered image aliases (ecr)': ecr, 'publish ordered image aliases (ghcr)': ghcr }, RUST)
    const messages = await messagesFor(run(104, 'failure', 'success'), [
        run(103, 'failure', 'failure'),
        run(102, 'failure', 'success'),
        run(101, 'success', 'success'),
    ])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /^Rust \(ecr\) \(Build and deploy rust container images\) ordered tagging failed in 3/)
})

test('uses the failed channel job even when the workflow and alias succeeded', async () => {
    const run = (id) => entry(id, { [ALIAS]: 'success', [CHANNELS]: 'failure' }, CONTAINERS)
    const messages = await messagesFor(run(103), [run(102), run(101)])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /^PostHog shared-image channels \(Container Images CD\).*failed in 3/)
})

test('nearby completions decide their own streaks in completion order, with run ID as the tie-breaker', async () => {
    const trigger = nodeRun(103, 'failure')
    const completedEarlier = nodeRun(105, 'failure')
    completedEarlier.run.updated_at = nodeRun(102).run.updated_at
    const concurrent = nodeRun(104, 'failure')
    concurrent.run.updated_at = trigger.run.updated_at
    const runs = [concurrent, completedEarlier, trigger, nodeRun(101, 'failure'), nodeRun(100, 'success')]

    const [later, earlier] = await Promise.all(
        [concurrent, trigger].map(({ run }) => fakeHistory(runs).process(run))
    )
    assert.deepEqual(later, [])
    assert.equal(earlier.length, 1)
    assert.match(earlier[0], /3 consecutive runs \(<https:\/\/example.com\/runs\/103\|newest failure>/)
    assert.ok(earlier[0].includes('<https://example.com/runs/101|first failure>'))
})

test('exits before reading history on a rerun, including a rerun that succeeded', async () => {
    const trigger = nodeRun(101, 'success')
    const history = fakeHistory([trigger, ...failingHistory(3)])
    assert.deepEqual(await history.process({ ...trigger.run, run_attempt: 2 }), [])
    assert.deepEqual(history.calls, [])
})

test('a skipped, cancelled, or absent triggering job only needs the triggering jobs page', async () => {
    for (const conclusion of ['skipped', 'cancelled', null]) {
        const trigger = nodeRun(101, conclusion)
        const history = fakeHistory([trigger, ...failingHistory(3)])
        assert.deepEqual(await history.process(trigger.run), [])
        assert.deepEqual(history.calls, [101])
    }
})

test('does not read further once a success has three preceding failures', async () => {
    const trigger = nodeRun(101, 'success')
    const history = fakeHistory([trigger, ...failingHistory(5)])
    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /recovered/)
    assert.deepEqual(history.calls, [101, 'list runs', 100, 99, 98])
})

test('does not announce an exact failure streak if the history limit hides its start', async () => {
    const [trigger, ...older] = failingHistory(3)
    const skipped = Array.from({ length: 99 }, (_, index) => nodeRun(97 - index, 'skipped'))
    const history = fakeHistory([trigger, ...older, ...skipped])

    assert.deepEqual(await history.process(trigger.run), [])
    assert.equal(history.calls.length, 101)
})
