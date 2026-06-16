// Run with: node --test .github/scripts/ci-alerts-devex.test.js
//
// Detection from the GitHub API is exercised alongside Slack reconciliation:
// Slack is the source of truth, so the key cases are "open incident found in
// history → update, never a duplicate" and the resolve/strikethrough lifecycle.

const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const ciAlertsDevex = require('./ci-alerts-devex')

const T_BASE = new Date('2026-04-09T12:00:00Z')
const minutes = (n) => new Date(T_BASE.getTime() + n * 60000)

// Minimal call-recording mock (no jest in the node:test runner).
function recordingFn(impl) {
    const fn = (...args) => {
        fn.calls.push(args)
        return impl ? impl(...args) : undefined
    }
    fn.calls = []
    return fn
}

// Workflow-run objects in raw listWorkflowRuns shape, conclusions newest-first.
function runs(name, conclusions) {
    return conclusions.map((conclusion, i) => ({
        name,
        conclusion,
        head_sha: `sha_${name}_${i}`,
        html_url: `https://github.com/runs/${name}/${i}`,
        updated_at: minutes(-(i * 5)).toISOString(),
    }))
}

const failingRuns = (name, failCount) => runs(name, [...Array(failCount).fill('failure'), ...Array(5).fill('success')])

const allPassing = () => ({
    'ci-backend.yml': runs('Backend CI', ['success']),
    'ci-frontend.yml': runs('Frontend CI', ['success']),
})

// listCommits + listWorkflowRuns aligned by SHA. Each element is a
// {workflowFile: conclusion} map for one commit (newest first).
function commitsWithRuns(perCommitConclusions) {
    const commits = perCommitConclusions.map((_, i) => ({
        sha: `commit_sha_${i}`,
        html_url: `https://github.com/commit/commit_sha_${i}`,
        author: { login: 'dev' },
        commit: { message: `commit ${i}`, author: { name: 'dev', date: minutes(-(i * 5)).toISOString() } },
    }))
    const runsByWorkflow = {}
    perCommitConclusions.forEach((conclusionsMap, i) => {
        for (const [wf, conclusion] of Object.entries(conclusionsMap)) {
            if (!runsByWorkflow[wf]) runsByWorkflow[wf] = []
            runsByWorkflow[wf].push({
                name: wf === 'ci-backend.yml' ? 'Backend CI' : 'Frontend CI',
                conclusion,
                head_sha: `commit_sha_${i}`,
                html_url: `https://github.com/runs/${wf}/${i}`,
                updated_at: minutes(-(i * 5)).toISOString(),
            })
        }
    })
    return { commits, runsByWorkflow }
}

function createGithubMock(workflowRuns, { commits = [] } = {}) {
    return {
        rest: {
            actions: {
                listWorkflowRuns: ({ workflow_id }) =>
                    Promise.resolve({ data: { workflow_runs: workflowRuns[workflow_id] || [] } }),
            },
            repos: {
                listCommits: () => Promise.resolve({ data: commits }),
            },
        },
    }
}

function makeSlack(history = []) {
    return {
        postMessage: recordingFn(() => ({ ok: true, ts: '111.222' })),
        update: recordingFn(() => ({ ok: true })),
        history: recordingFn(() => ({ ok: true, messages: history })),
    }
}

// An open incident anchor as conversations.history would return it.
const activeAnchor = (payload = {}) => ({
    ts: '999.000',
    metadata: {
        event_type: 'master_ci_incident',
        event_payload: {
            status: 'active',
            since: minutes(-30).toISOString(),
            workflows: ['Backend CI'],
            commitActive: false,
            ...payload,
        },
    },
})

// One failure that landed `redMins` ago, preceded by a green run. count=1 (below the streak
// threshold), so this drives the wall-clock arm in isolation; redForMins == redMins.
const failingFor = (redMins, name = 'Backend CI') => [
    { name, conclusion: 'failure', head_sha: `f_${redMins}`, html_url: `https://github.com/runs/${name}/f`, updated_at: minutes(-redMins).toISOString() },
    { name, conclusion: 'success', head_sha: `g_${redMins}`, html_url: `https://github.com/runs/${name}/g`, updated_at: minutes(-(redMins + 30)).toISOString() },
]

// A single commit `ageMins` old — drives recentActivity. No matching run SHA, so it classifies
// 'unknown' and does not trip the commit-streak arm.
const commitsAt = (ageMins) => [
    {
        sha: 'c0',
        html_url: 'https://github.com/commit/c0',
        author: { login: 'dev' },
        commit: { message: 'c', author: { name: 'dev', date: minutes(-ageMins).toISOString() } },
    },
]

function run(github, { history = [], now = minutes(0), env = {} } = {}) {
    const outputs = {}
    const core = { setOutput: (k, v) => (outputs[k] = v), info: () => {}, warning: () => {} }
    const slack = makeSlack(history)
    Object.assign(process.env, {
        SLACK_CHANNEL: 'C0AS64N6DJL',
        GATING_WORKFLOWS: 'ci-backend.yml,ci-frontend.yml',
        WORKFLOW_FAILURE_STREAK_THRESHOLD: '5',
        // Reset to production defaults every run so a per-test override can't leak via process.env.
        WORKFLOW_FAILURE_MINUTES_THRESHOLD: '20',
        ACTIVITY_WINDOW_MINUTES: '120',
        COMMIT_FAILURE_STREAK_THRESHOLD: '10',
        ...env,
    })
    return ciAlertsDevex(
        { context: { repo: { owner: 'PostHog', repo: 'posthog' } }, github, core },
        { now, slack }
    ).then(() => ({ slack, outputs }))
}

describe('ci-alerts-devex', () => {
    it('no-op when all workflows pass and no incident is open', async () => {
        const { slack, outputs } = await run(createGithubMock(allPassing()))
        assert.equal(outputs.action, 'none')
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls.length, 0)
    })

    for (const conclusion of ['failure', 'timed_out']) {
        it(`posts a new anchor + initial thread on 5 consecutive ${conclusion}`, async () => {
            const github = createGithubMock({
                'ci-backend.yml': runs('Backend CI', Array(5).fill(conclusion)),
                'ci-frontend.yml': runs('Frontend CI', ['success']),
            })
            const { slack, outputs } = await run(github)

            assert.equal(outputs.action, 'create')
            assert.equal(slack.update.calls.length, 0)
            assert.equal(slack.postMessage.calls.length, 2)

            const anchor = slack.postMessage.calls[0][0]
            assert.match(anchor.text, /Master is red/) // notification fallback
            assert.equal(anchor.attachments[0].color, '#E01E5A')
            const body = JSON.stringify(anchor.attachments)
            assert.match(body, /Backend CI/)
            assert.match(body, /5 failed runs in a row/)
            assert.match(body, /actions\/workflows\/ci-backend\.yml\?query=branch/) // per-workflow runs link
            assert.equal(anchor.metadata.event_type, 'master_ci_incident')
            assert.equal(anchor.metadata.event_payload.status, 'active')
            assert.deepEqual(
                anchor.metadata.event_payload.workflows.map((w) => w.name),
                ['Backend CI']
            )

            const thread = slack.postMessage.calls[1][0]
            assert.equal(thread.thread_ts, '111.222')
            assert.match(thread.text, /Backend CI/)
            assert.match(thread.text, /is now failing master/)
        })
    }

    it('updates the existing anchor instead of posting a duplicate (regression)', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', Array(8).fill('failure')),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { slack, outputs } = await run(github, { history: [activeAnchor()] })

        assert.equal(outputs.action, 'update')
        assert.equal(slack.update.calls.length, 1)
        // Same failing set → anchor refresh only, no thread spam, no new anchor.
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls[0][0].ts, '999.000')
        assert.equal(slack.update.calls[0][0].attachments[0].color, '#E01E5A')
        assert.equal(slack.update.calls[0][0].metadata.event_payload.status, 'active')
    })

    it('threads a reply when a new workflow joins the failing set', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': failingRuns('Frontend CI', 5),
        })
        const { slack, outputs } = await run(github, { history: [activeAnchor({ workflows: ['Backend CI'] })] })

        assert.equal(outputs.action, 'update')
        assert.equal(slack.update.calls.length, 1)
        assert.equal(slack.postMessage.calls.length, 1)
        const thread = slack.postMessage.calls[0][0].text
        assert.match(thread, /now also failing/)
        assert.match(thread, /Frontend CI/)
        assert.match(thread, /actions\/workflows\/ci-frontend\.yml\?query=branch/)
    })

    it('strikes through the anchor and threads recovery on resolve', async () => {
        const { slack, outputs } = await run(createGithubMock(allPassing()), {
            history: [activeAnchor({ workflows: ['Backend CI', 'E2E CI Playwright'] })],
        })

        assert.equal(outputs.action, 'resolve')
        const resolved = slack.update.calls[0][0]
        assert.equal(resolved.ts, '999.000')
        assert.match(resolved.text, /Master recovered/) // notification fallback
        assert.equal(resolved.attachments[0].color, '#2EB67D')
        const body = JSON.stringify(resolved.attachments)
        assert.match(body, /Master recovered/)
        assert.match(body, /~Backend CI, E2E CI Playwright~/) // struck-through cleared list
        assert.equal(resolved.metadata.event_payload.status, 'resolved')
        assert.match(slack.postMessage.calls[0][0].text, /master green again/)
    })

    it('opens an incident on a commit-failure streak with no single-workflow streak', async () => {
        // Alternating culprits: every commit is red, but neither workflow
        // reaches 5 consecutive failures on its own.
        const { commits, runsByWorkflow } = commitsWithRuns(
            Array.from({ length: 10 }, (_, i) =>
                i % 2 === 0
                    ? { 'ci-backend.yml': 'failure', 'ci-frontend.yml': 'success' }
                    : { 'ci-backend.yml': 'success', 'ci-frontend.yml': 'failure' }
            )
        )
        const { slack, outputs } = await run(createGithubMock(runsByWorkflow, { commits }))

        assert.equal(outputs.action, 'create')
        assert.equal(outputs.commit_streak, '10')
        const anchor = slack.postMessage.calls[0][0]
        const body = JSON.stringify(anchor.attachments)
        assert.match(body, /10 commits in a row failed a required check/)
        // No workflow crossed its own threshold → no per-workflow bullet lines.
        assert.doesNotMatch(body, /failed runs? in a row/)
        assert.equal(anchor.metadata.event_payload.commitActive, true)
    })

    it('merges both signals into one anchor', async () => {
        const { commits, runsByWorkflow } = commitsWithRuns(Array(10).fill({ 'ci-backend.yml': 'failure' }))
        const { slack, outputs } = await run(createGithubMock(runsByWorkflow, { commits }))

        assert.equal(outputs.action, 'create')
        const body = JSON.stringify(slack.postMessage.calls[0][0].attachments)
        assert.match(body, /Backend CI/)
        assert.match(body, /10 failed runs in a row/)
        assert.match(body, /10 commits in a row failed a required check/)
    })

    it('filters cancelled and skipped runs from the consecutive count', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', [
                'failure',
                'cancelled',
                'failure',
                'skipped',
                'failure',
                'failure',
                'failure',
                'success',
            ]),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { slack, outputs } = await run(github)
        assert.equal(outputs.action, 'create')
        assert.match(JSON.stringify(slack.postMessage.calls[0][0].attachments), /5 failed runs in a row/)
    })

    it('stays quiet below threshold with no open incident', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', ['failure', 'failure', 'success']),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { slack, outputs } = await run(github)
        assert.equal(outputs.action, 'none')
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls.length, 0)
    })

    it('opens via the wall-clock arm when red past the threshold and master is being pushed', async () => {
        // 1 failure (below the 5-streak) but red 25m, recent push → time arm trips.
        const github = createGithubMock(
            { 'ci-backend.yml': failingFor(25), 'ci-frontend.yml': runs('Frontend CI', ['success']) },
            { commits: commitsAt(3) }
        )
        const { slack, outputs } = await run(github)
        assert.equal(outputs.action, 'create')
        const body = JSON.stringify(slack.postMessage.calls[0][0].attachments)
        assert.match(body, /Backend CI/)
        assert.match(body, /red for 25m/)
        assert.doesNotMatch(body, /failed runs? in a row/) // duration-only bullet omits the count
    })

    it('stays silent when red past the threshold but no recent push (quiet weekend)', async () => {
        const github = createGithubMock(
            { 'ci-backend.yml': failingFor(2400), 'ci-frontend.yml': runs('Frontend CI', ['success']) },
            { commits: commitsAt(3000) }
        )
        const { slack, outputs } = await run(github)
        assert.equal(outputs.action, 'none')
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls.length, 0)
    })

    it('keeps a stale-red incident open (updates, never resolves) once activity goes quiet', async () => {
        const github = createGithubMock(
            { 'ci-backend.yml': failingFor(2400), 'ci-frontend.yml': runs('Frontend CI', ['success']) },
            { commits: commitsAt(3000) }
        )
        const { slack, outputs } = await run(github, { history: [activeAnchor()] })
        assert.equal(outputs.action, 'update')
        assert.equal(slack.update.calls[0][0].attachments[0].color, '#E01E5A')
        assert.equal(slack.update.calls[0][0].metadata.event_payload.status, 'active')
    })

    // Wall-clock arm gate: (red minutes, last-push age, threshold override) → action.
    for (const [scenario, { red, commitAge, env = {} }, expected] of [
        ['stays quiet below the minutes threshold', { red: 15, commitAge: 3 }, 'none'],
        ['fails closed with no commit data', { red: 25 }, 'none'],
        ['honors a custom minutes threshold', { red: 12, commitAge: 3, env: { WORKFLOW_FAILURE_MINUTES_THRESHOLD: '10' } }, 'create'],
        ['opens just inside the activity window', { red: 30, commitAge: 119 }, 'create'],
        ['stays quiet just outside the activity window', { red: 30, commitAge: 121 }, 'none'],
    ]) {
        it(`wall-clock arm ${scenario}`, async () => {
            const github = createGithubMock(
                { 'ci-backend.yml': failingFor(red), 'ci-frontend.yml': runs('Frontend CI', ['success']) },
                commitAge == null ? {} : { commits: commitsAt(commitAge) }
            )
            const { outputs } = await run(github, { env })
            assert.equal(outputs.action, expected)
        })
    }

    describe('formatDuration', () => {
        for (const [mins, expected] of [
            [5, '5m'],
            [59, '59m'],
            [60, '1h'],
            [88, '1h 28m'],
            [192, '3h 12m'],
        ]) {
            it(`formats ${mins} minutes as ${expected}`, () => {
                assert.equal(ciAlertsDevex.formatDuration(mins), expected)
            })
        }
    })
})
