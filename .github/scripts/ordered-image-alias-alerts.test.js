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

function fakeHistory(
    entries,
    { firstAttempts = [], stalePages = 0, addedAfterFirstPage, slackResponse = { ok: true, json: async () => ({ ok: true }) } } = {}
) {
    const calls = []
    const delays = []
    const messages = []
    const runs = entries.map(({ run }) => run).sort((a, b) => b.created_at.localeCompare(a.created_at))
    const jobs = new Map(entries.map(({ run, jobs }) => [run.id, jobs]))
    const attempts = new Map(firstAttempts.map((entry) => [entry.run.id, entry]))
    const jobsPage = (available, page, perPage) => {
        const start = (page - 1) * perPage
        return { data: { jobs: available.slice(start, start + perPage), total_count: available.length } }
    }
    const github = {
        rest: {
            actions: {
                async listJobsForWorkflowRun({ run_id, per_page, page }) {
                    calls.push(page === 1 ? run_id : `list jobs ${run_id} page ${page}`)
                    assert.ok(jobs.has(run_id))
                    return jobsPage(jobs.get(run_id), page, per_page)
                },
                async getWorkflowRunAttempt({ run_id, attempt_number, ...repo }) {
                    calls.push(`get run ${run_id} attempt ${attempt_number}`)
                    assert.deepEqual(repo, { owner: 'example', repo: 'images' })
                    assert.equal(attempt_number, 1)
                    return { data: attempts.get(run_id).run }
                },
                async listJobsForWorkflowRunAttempt({ run_id, attempt_number, per_page, page, ...repo }) {
                    calls.push(`list jobs ${run_id} attempt ${attempt_number} page ${page}`)
                    assert.deepEqual(repo, { owner: 'example', repo: 'images' })
                    assert.equal(attempt_number, 1)
                    return jobsPage(attempts.get(run_id)?.jobs ?? jobs.get(run_id), page, per_page)
                },
                async listWorkflowRuns(params) {
                    calls.push(`list runs ${params.page}`)
                    assert.equal(params.workflow_id, 17)
                    assert.equal(params.branch, 'master')
                    assert.equal(params.event, 'push')
                    assert.equal(params.status, 'completed')
                    assert.match(params.created, /^<=/)
                    const visible = params.page > 1 && addedAfterFirstPage ? [addedAfterFirstPage, ...runs] : runs
                    const matching = visible.filter((run) => run.created_at <= params.created.slice(2))
                    if (params.page === 1 && stalePages > 0) {
                        stalePages--
                        matching.shift()
                    }
                    const start = (params.page - 1) * params.per_page
                    return { data: { workflow_runs: matching.slice(start, start + params.per_page).map((run) => ({ ...run })) } }
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
                'Publish ordered image alias for Node.js (Build and deploy node container image) succeeded after at least 3 consecutive failures (<https://example.com/runs/101|successful run>).',
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
        'Shared-image channel publication did not complete cleanly. Workers on channels that were not verified may remain on their previous image. Check the linked run for the failure and any channel results.'
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

test('posts the third first-attempt failure once when the latest attempt has no alias conclusion', async () => {
    const [trigger, ...predecessors] = failingHistory(3)
    const latestJobs = { ...trigger, jobs: [{ name: ALIAS, conclusion: null }] }
    const history = fakeHistory([latestJobs, ...predecessors], { firstAttempts: [trigger] })

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/100|newest failure>'))
})

test('requests attempt 1 jobs for the triggering run', async () => {
    const trigger = nodeRun(101, 'failure')
    const history = fakeHistory([trigger])

    await history.process(trigger.run)
    assert.deepEqual(history.calls, ['list jobs 101 attempt 1 page 1', 'list runs 1'])
})

test('exits before reading history on a rerun, including a rerun that succeeded', async () => {
    const trigger = nodeRun(101, 'success')
    const history = fakeHistory([trigger, ...failingHistory(3)])
    assert.deepEqual(await history.process({ ...trigger.run, run_attempt: 2 }), [])
    assert.deepEqual(history.calls, [])
})

test('ignores a successful rerun event and posts one recovery on the next successful push', async () => {
    const [failed, ...predecessors] = failingHistory(3)
    const [alert] = await messagesFor(failed, predecessors)
    assert.match(alert, /failed in 3 consecutive runs/)

    const rerun = completedAt(nodeRun(failed.run.id, 'success'), 101)
    rerun.run.run_attempt = 2
    const recovered = nodeRun(102, 'success')
    const later = nodeRun(103, 'success')
    const history = fakeHistory([later, recovered, rerun, ...predecessors], { firstAttempts: [failed] })
    assert.deepEqual(await history.process(rerun.run), [])
    assert.deepEqual(history.calls, [])

    const recovery = 'Publish ordered image alias for Node.js (Build and deploy node container image) succeeded after at least 3 consecutive failures (<https://example.com/runs/102|successful run>).'
    assert.deepEqual(await history.process(recovered.run), [recovery])
    assert.deepEqual(await history.process(later.run), [recovery])
})

test('counts an older rerun at its first completion and keeps ordinary predecessors on the default route', async () => {
    const [trigger, ordinary, failed] = failingHistory(3)
    failed.run.html_url += '/attempts/1'
    failed.jobs.unshift(...Array.from({ length: 100 }, (_, i) => ({ name: `Build component ${i}`, conclusion: 'success' })))
    const rerun = completedAt(nodeRun(failed.run.id, 'success'), 101)
    rerun.run.run_attempt = 2
    const history = fakeHistory([trigger, ordinary, rerun], { firstAttempts: [failed] })

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/98/attempts/1|first failure>'))
    assert.deepEqual(history.calls, [
        'list jobs 100 attempt 1 page 1',
        'list runs 1',
        'get run 98 attempt 1',
        99,
        'list jobs 98 attempt 1 page 1',
        'list jobs 98 attempt 1 page 2',
    ])
})

test('a skipped, cancelled, or absent triggering job only needs the triggering jobs page', async () => {
    for (const conclusion of ['skipped', 'cancelled', null]) {
        const trigger = nodeRun(101, conclusion)
        const history = fakeHistory([trigger, ...failingHistory(3)])
        assert.deepEqual(await history.process(trigger.run), [])
        assert.deepEqual(history.calls, ['list jobs 101 attempt 1 page 1'])
    }
})

test('does not read further once a success has three preceding failures', async () => {
    const trigger = nodeRun(50000, 'success')
    const failures = [49999, 49998, 49997, 49996].map((id) => nodeRun(id, 'failure'))
    const older = Array.from({ length: 100 }, (_, index) => nodeRun(1000 - index, 'skipped'))
    const history = fakeHistory([trigger, ...failures, ...older])
    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /succeeded after at least 3 consecutive failures/)
    assert.deepEqual(history.calls, ['list jobs 50000 attempt 1 page 1', 'list runs 1', 49999, 49998, 49997])
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

test('stops after ten full pages without reading the jobs of unconfirmed runs', async () => {
    const trigger = nodeRun(2000, 'failure')
    const older = [nodeRun(1999, 'failure'), nodeRun(1998, 'failure')]
    const skipped = Array.from({ length: 997 }, (_, index) => nodeRun(1997 - index, 'skipped'))
    const history = fakeHistory([trigger, ...older, ...skipped, nodeRun(1000, 'success')])

    assert.deepEqual(await history.process(trigger.run), [])
    assert.deepEqual(history.calls, [
        'list jobs 2000 attempt 1 page 1',
        ...Array.from({ length: 10 }, (_, i) => `list runs ${i + 1}`),
    ])
})

test('withholds an alert when three failures pass the six-hour bound and the first success is beyond ten full pages', async () => {
    const trigger = nodeRun(50000, 'failure')
    const recentFailures = [49999, 49998].map((id) => nodeRun(id, 'failure'))
    const skipped = Array.from({ length: 997 }, (_, index) => nodeRun(1000 - index, 'skipped'))
    const successAfterCap = nodeRun(3, 'success')
    const history = fakeHistory([trigger, ...recentFailures, ...skipped, successAfterCap])

    assert.deepEqual(await history.process(trigger.run), [])
    assert.deepEqual(history.calls, [
        'list jobs 50000 attempt 1 page 1',
        'list runs 1',
        49999,
        49998,
        ...Array.from({ length: 9 }, (_, i) => `list runs ${i + 2}`),
    ])
})

function completedAt(entry, seconds) {
    entry.run.updated_at = new Date(seconds * 1000).toISOString()
    return entry
}

function pageBoundaryHistory(recentFailures, lastOnFirstPage, firstOnNextPage) {
    return [
        nodeRun(1000, 'failure'),
        ...Array.from({ length: 98 }, (_, i) => nodeRun(999 - i, i < recentFailures ? 'failure' : 'skipped')),
        nodeRun(901, lastOnFirstPage),
        nodeRun(900, firstOnNextPage),
    ]
}

test('cross-page completion order 1000 failure, 999 failure, 900 success, 901 failure has a streak of two', async () => {
    const [trigger, ...older] = pageBoundaryHistory(1, 'failure', 'success')
    completedAt(older.at(-1), 902)
    const history = fakeHistory([trigger, ...older])

    assert.deepEqual(await history.process(trigger.run), [])
    assert.deepEqual(history.calls.slice(0, 4), ['list jobs 1000 attempt 1 page 1', 'list runs 1', 'list runs 2', 999])
    assert.equal(history.calls.at(-1), 900)
    assert.ok(!history.calls.includes(901))
})

test('cross-page completion order 1000 through 989 failures, 900 failure, 901 success has a streak of thirteen', async () => {
    const [trigger, ...older] = pageBoundaryHistory(11, 'success', 'failure')
    completedAt(older.at(-1), 902)
    const history = fakeHistory([trigger, ...older])

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 13 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/900|first failure>'))
})

test('waits at the six-hour bound for a higher-ID success on the next page', async () => {
    const trigger = nodeRun(50000, 'failure')
    const recentFailure = nodeRun(49999, 'failure')
    const skipped = Array.from({ length: 97 }, (_, i) => nodeRun(1000 - i, 'skipped'))
    const completionAtBound = 900 + 6 * 60 * 60
    const waitingFailure = completedAt(nodeRun(900, 'failure'), completionAtBound)
    const unreadSuccess = completedAt(nodeRun(901, 'success'), completionAtBound)
    unreadSuccess.run.created_at = waitingFailure.run.created_at
    const history = fakeHistory([trigger, recentFailure, ...skipped, waitingFailure, unreadSuccess])

    assert.deepEqual(await history.process(trigger.run), [])
    assert.deepEqual(history.calls, ['list jobs 50000 attempt 1 page 1', 'list runs 1', 49999, 'list runs 2', 901])
})

test('orders a later-created success after two earlier-created failures inside one page', async () => {
    const messages = await messagesFor(nodeRun(103, 'failure'), [
        nodeRun(102, 'success'),
        completedAt(nodeRun(101, 'failure'), 102.5),
        completedAt(nodeRun(100, 'failure'), 102.25),
    ])

    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
    assert.ok(messages[0].includes('<https://example.com/runs/100|first failure>'))
})

test('does not count a failure twice when a new completion shifts the next page by one run', async () => {
    const [trigger, ...older] = pageBoundaryHistory(0, 'failure', 'success')
    completedAt(trigger, 1002)
    const newRun = completedAt(nodeRun(1001, 'failure'), 1003).run
    const history = fakeHistory([trigger, ...older], { addedAfterFirstPage: newRun })

    assert.deepEqual(await history.process(trigger.run), [])
    assert.equal(history.calls.filter((call) => call === 901).length, 1)
})

test('counts the alias job from page 2 and reads exactly 100 jobs in one call', async () => {
    const [trigger, ...older] = failingHistory(3)
    for (const [entry, unrelated] of [[trigger, 100], [older[0], 99]]) {
        entry.jobs.unshift(...Array.from({ length: unrelated }, (_, i) => ({ name: `Build component ${i}`, conclusion: 'success' })))
    }
    const history = fakeHistory([trigger, ...older])

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
    assert.deepEqual(history.calls, [
        'list jobs 100 attempt 1 page 1',
        'list jobs 100 attempt 1 page 2',
        'list runs 1',
        99,
        98,
    ])
})

test('retries a stale first page and posts once from fresh history', async () => {
    const [trigger, ...older] = failingHistory(3)
    const history = fakeHistory([trigger, ...older], { stalePages: 1 })

    const messages = await history.process(trigger.run)
    assert.equal(messages.length, 1)
    assert.match(messages[0], /failed in 3 consecutive runs/)
    assert.equal(history.delays.length, 1)
    assert.deepEqual(history.calls, ['list jobs 100 attempt 1 page 1', 'list runs 1', 'list runs 1', 99, 98])
})

test('fails visibly when the first page stays stale', async () => {
    const [trigger, ...older] = failingHistory(3)
    const history = fakeHistory([trigger, ...older], { stalePages: 2 })

    await assert.rejects(history.process(trigger.run), /Stale Actions history: run 100 is missing from the first page/)
    assert.deepEqual(history.messages, [])
    assert.equal(history.delays.length, 1)
    assert.deepEqual(history.calls, ['list jobs 100 attempt 1 page 1', 'list runs 1', 'list runs 1'])
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
