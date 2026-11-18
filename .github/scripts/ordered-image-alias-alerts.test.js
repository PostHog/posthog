const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const { join } = require('node:path')
const { test } = require('node:test')

const notify = require('./ordered-image-alias-alerts')

const NODE = 'Build and deploy node container image'
const RUST = 'Build and deploy rust container images'
const CONTAINERS = 'Container Images CD'
const CREDENTIALS = 'Credentials Service Container Image CD'
const ALIAS = 'Publish ordered image alias'
const CHANNELS = 'Publish eligible shared-image channels'

function entry(id, laneResults, name = NODE, conclusion = 'success') {
    const time = new Date(id * 1000).toISOString()
    return {
        run: {
            id,
            name,
            conclusion,
            workflow_id: 17,
            run_attempt: 1,
            created_at: time,
            updated_at: time,
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

function fakeHistory(entries, { stalePages = 0, slackResponse = { ok: true, json: async () => ({ ok: true }) } } = {}) {
    const calls = []
    const delays = []
    const messages = []
    const runs = entries.map(({ run }) => run).sort((a, b) => b.created_at.localeCompare(a.created_at))
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
                    calls.push(`list runs ${params.page}`)
                    assert.equal(params.workflow_id, 17)
                    assert.equal(params.branch, 'master')
                    assert.equal(params.event, 'push')
                    assert.equal(params.status, 'completed')
                    assert.match(params.created, /^<=/)
                    const matching = runs.filter((run) => run.created_at <= params.created.slice(2))
                    if (params.page === 1 && stalePages > 0) {
                        stalePages--
                        matching.shift()
                    }
                    const start = (params.page - 1) * params.per_page
                    return { data: { workflow_runs: matching.slice(start, start + params.per_page) } }
                },
            },
        },
    }
    return {
        calls,
        delays,
        messages,
        async process(run) {
            await notify(
                { context: { repo: { owner: 'example', repo: 'images' }, payload: { workflow_run: run } }, github },
                {
                    token: 'example-token',
                    async delay(ms) {
                        delays.push(ms)
                    },
                    async fetch(url, params) {
                        assert.equal(url, 'https://slack.com/api/chat.postMessage')
                        assert.equal(params.method, 'POST')
                        const { channel, text } = JSON.parse(params.body)
                        assert.equal(channel, 'C0B11J29GP9')
                        messages.push(text)
                        return slackResponse
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
            assert.ok(messages[0].endsWith(
                'A missing or unverified ordered alias can leave Kargo without Freight for the Node.js image, so deploys stay on the previous build.'
            ))
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
            count < 3 ? [] : [
                'Publish ordered image alias for Node.js (Build and deploy node container image) succeeded after at least three consecutive failures (<https://example.com/runs/101|successful run>).',
            ]
        )
    })
}

test('ignores skipped, cancelled and absent jobs between failures', async () => {
    const messages = await messagesFor(nodeRun(110, 'failure'), [
        nodeRun(109, 'skipped'),
        nodeRun(108, 'failure'),
        nodeRun(106, 'cancelled'),
        nodeRun(105, null),
        nodeRun(104, 'failure'),
        nodeRun(103, 'success'),
    ])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /3 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/104|first failure>'))
})

for (const registry of ['ghcr', 'ecr']) {
    test(`tracks the Rust ${registry} failure separately from the other registry`, async () => {
        const other = registry === 'ghcr' ? 'ecr' : 'ghcr'
        const run = (id, own, peer) =>
            entry(id, { [`publish ordered image aliases (${registry})`]: own, [`publish ordered image aliases (${other})`]: peer }, RUST)
        const messages = await messagesFor(run(104, 'failure', 'success'), [
            run(103, 'failure', 'failure'),
            run(102, 'failure', 'success'),
            run(101, 'success', 'success'),
        ])
        assert.equal(messages.length, 1)
        assert.ok(messages[0].startsWith(`Rust (${registry}) (Build and deploy rust container images) failed in 3`))
        assert.ok(messages[0].endsWith(
            `A missing or unverified ordered alias can leave Kargo without Freight for the Rust images in ${registry.toUpperCase()}, so deploys using that registry stay on the previous build.`
        ))
    })
}

test('uses the failed channel job even when the workflow and alias succeeded', async () => {
    const run = (id) => entry(id, { [ALIAS]: 'success', [CHANNELS]: 'failure' }, CONTAINERS)
    const messages = await messagesFor(run(103), [run(102), run(101)])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /^PostHog shared-image channels \(Container Images CD\).*failed in 3/)
    assert.ok(messages[0].endsWith(
        'One or more shared-image channels were not published, so workers on those channels stay on their previous image. See the linked run for publication evidence.'
    ))
})

test('posts the PostHog alias and channels failures on separate lines in one request', async () => {
    const run = (id) => entry(id, { [ALIAS]: 'failure', [CHANNELS]: 'failure' }, CONTAINERS)
    const messages = await messagesFor(run(103), [run(102), run(101)])
    assert.equal(messages.length, 1)
    const lines = messages[0].split('\n')
    assert.equal(lines.length, 2)
    assert.match(lines[0], /^PostHog \(Container Images CD\) failed in 3/)
    assert.ok(lines[0].endsWith(
        'A missing or unverified ordered alias can leave Kargo without Freight for the PostHog image, so deploys stay on the previous build.'
    ))
    assert.match(lines[1], /^PostHog shared-image channels \(Container Images CD\) failed in 3/)
})

test('limits the credentials consequence to the affected registry', async () => {
    const run = (id) => entry(id, { [ALIAS]: 'failure' }, CREDENTIALS)
    const messages = await messagesFor(run(103), [run(102), run(101)])
    assert.equal(messages.length, 1)
    assert.ok(messages[0].endsWith(
        'A missing or unverified ordered alias can leave Kargo without Freight for the credentials service image in the affected registry, so deploys using that registry stay on the previous build.'
    ))
})

test('counts timed-out jobs as failures in the trigger and history', async () => {
    const messages = await messagesFor(nodeRun(103, 'timed_out'), [nodeRun(102, 'failure'), nodeRun(101, 'timed_out')])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
})

test('counts failed jobs in runs that were cancelled later', async () => {
    const messages = await messagesFor(nodeRun(103, 'failure', 'cancelled'), [
        nodeRun(102, 'failure', 'cancelled'),
        nodeRun(101, 'failure'),
    ])
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
})

test('nearby completions decide their own streaks in completion order, with run ID as the tie-breaker', async () => {
    const trigger = nodeRun(103, 'failure')
    const completedEarlier = nodeRun(105, 'failure')
    completedEarlier.run.updated_at = nodeRun(102).run.updated_at
    completedEarlier.run.created_at = nodeRun(101).run.created_at
    const concurrent = nodeRun(104, 'failure')
    concurrent.run.updated_at = trigger.run.updated_at
    concurrent.run.created_at = nodeRun(102).run.created_at
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
    assert.match(messages[0], /succeeded after at least three consecutive failures/)
    assert.deepEqual(history.calls, [101, 'list runs 1', 100, 99, 98])
})

test('counts a sparse streak of 13 when the preceding success is on page 2', async () => {
    const trigger = nodeRun(300, 'failure')
    const older = Array.from({ length: 118 }, (_, i) => {
        const distance = i + 1
        const conclusion = distance === 117 ? 'success' : distance % 9 === 0 ? 'failure' : 'skipped'
        return nodeRun(300 - distance, conclusion)
    })
    const history = fakeHistory([trigger, ...older])

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 13 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/192|first failure>'))
    assert.equal(history.calls.length, 120)
    assert.equal(history.calls.at(-1), 183)
})

test('stops after ten full pages without announcing an unsettled failure streak', async () => {
    const trigger = nodeRun(2000, 'failure')
    const older = [nodeRun(1999, 'failure'), nodeRun(1998, 'failure')]
    const skipped = Array.from({ length: 997 }, (_, index) => nodeRun(1997 - index, 'skipped'))
    const history = fakeHistory([trigger, ...older, ...skipped, nodeRun(1000, 'success')])

    assert.deepEqual(await history.process(trigger.run), [])
    assert.equal(history.calls.length, 1010)
    assert.ok(!history.calls.includes('list runs 11'))
    assert.ok(!history.calls.includes(1000))
})

test('retries a stale first page and posts once from fresh history', async () => {
    const [trigger, ...older] = failingHistory(3)
    const history = fakeHistory([trigger, ...older], { stalePages: 1 })

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
    assert.equal(history.delays.length, 1)
    assert.deepEqual(history.calls, [100, 'list runs 1', 'list runs 1', 99, 98])
})

test('fails visibly when the first page stays stale', async () => {
    const [trigger, ...older] = failingHistory(3)
    const history = fakeHistory([trigger, ...older], { stalePages: 2 })

    await assert.rejects(history.process(trigger.run), /Stale Actions history: run 100 is missing from the first page/)
    assert.deepEqual(history.messages, [])
    assert.equal(history.delays.length, 1)
    assert.deepEqual(history.calls, [100, 'list runs 1', 'list runs 1'])
})

test('reports the HTTP status for a non-JSON Slack failure', async () => {
    const [trigger, ...older] = failingHistory(3)
    const history = fakeHistory([trigger, ...older], {
        slackResponse: { ok: false, status: 502, json: async () => JSON.parse('Bad Gateway') },
    })

    await assert.rejects(history.process(trigger.run), /Slack chat.postMessage failed with HTTP 502/)
    assert.equal(history.messages.length, 1)
})

test('reports a Slack rejection in a successful HTTP response', async () => {
    const [trigger, ...older] = failingHistory(3)
    const history = fakeHistory([trigger, ...older], {
        slackResponse: { ok: true, json: async () => ({ ok: false, error: 'invalid_auth' }) },
    })

    await assert.rejects(history.process(trigger.run), /Slack chat.postMessage failed: invalid_auth/)
    assert.equal(history.messages.length, 1)
})

test('the alert trigger and lane names match the publisher workflows', () => {
    const workflow = (file) => JSON.parse(
        execFileSync('yq', ['-o=json', '-I=0', '.', join(__dirname, '..', 'workflows', file)], { encoding: 'utf8' })
    )
    const publishers = [
        'container-images-cd.yml',
        'ci-nodejs-container.yml',
        'rust-docker-build.yml',
        'cd-credentials-service-image.yml',
    ].map(workflow)
    const trigger = workflow('ordered-image-alias-alerts.yml').on.workflow_run.workflows
    const names = publishers.map(({ name }) => name).sort()

    assert.deepEqual([...trigger].sort(), names, 'workflow_run names must match the publisher workflows')
    assert.deepEqual(Object.keys(notify.LANES).sort(), names, 'lane workflow names must match the publisher workflows')
    for (const { name, jobs } of publishers) {
        const alias = jobs.ordered_image_alias
        const registries = alias.strategy?.matrix?.registry
        const jobNames = registries
            ? registries.map((registry) => alias.name.replace(/\$\{\{\s*matrix\.registry\s*\}\}/g, registry))
            : [alias.name]
        if (jobs.shared_image_channels) {
            jobNames.push(jobs.shared_image_channels.name)
        }
        assert.deepEqual(
            notify.LANES[name].map(({ job }) => job).sort(),
            jobNames.sort(),
            `lane job names must match ${name}`
        )
    }
})
