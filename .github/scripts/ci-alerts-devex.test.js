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
        status: 'completed',
        conclusion,
        head_sha: `sha_${name}_${i}`,
        html_url: `https://github.com/runs/${name}/${i}`,
        updated_at: minutes(-(i * 5)).toISOString(),
    }))
}

const failingRuns = (name, failCount) => runs(name, [...Array(failCount).fill('failure'), ...Array(5).fill('success')])

// A non-terminal Backend CI run (no conclusion yet); status defaults to in_progress.
const nonTerminalRun = (key, status = 'in_progress') => ({
    name: 'Backend CI',
    status,
    conclusion: null,
    head_sha: key,
    html_url: `https://github.com/runs/${key}`,
    created_at: minutes(0).toISOString(),
    updated_at: minutes(0).toISOString(),
})

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
                status: 'completed',
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
    { name, status: 'completed', conclusion: 'failure', head_sha: `f_${redMins}`, html_url: `https://github.com/runs/${name}/f`, updated_at: minutes(-redMins).toISOString() },
    { name, status: 'completed', conclusion: 'success', head_sha: `g_${redMins}`, html_url: `https://github.com/runs/${name}/g`, updated_at: minutes(-(redMins + 30)).toISOString() },
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
        { now, slack, sleep: () => Promise.resolve() }
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

    // --- Stale-bridge duration ---
    const failureRun = (name, key, createdAt, updatedAt) => ({
        name,
        status: 'completed',
        conclusion: 'failure',
        head_sha: `${name}_${key}`,
        html_url: `https://github.com/runs/${name}/${key}`,
        created_at: createdAt,
        updated_at: updatedAt,
    })
    const pushAt = (iso) => [
        { sha: 'push', html_url: 'https://github.com/commit/push', author: { login: 'dev' }, commit: { message: 'p', author: { name: 'dev', date: iso } } },
    ]
    // A runs page anchored ~3 days back — the shape both observed phantoms ("red 70h", "red 141h")
    // were built from.
    const stalePage = (conclusion = 'failure') => [
        { ...failureRun('Backend CI', 'stale1', minutes(-4200).toISOString(), minutes(-4186).toISOString()), conclusion },
        { ...failureRun('Backend CI', 'stale2', minutes(-4215).toISOString(), minutes(-4201).toISOString()), conclusion },
    ]

    it('bridged stale failures do not inflate the displayed duration (regression)', async () => {
        // Recent failure + stale failure (the cancelled runs between are dropped) → the detection
        // streak spans multiple days. Must still open, but report the recent contiguous red.
        const now = minutes(13)
        const github = createGithubMock(
            {
                'ci-rust.yml': [
                    failureRun('Rust CI', 'recent', minutes(-9).toISOString(), minutes(5).toISOString()),
                    failureRun('Rust CI', 'stale', minutes(-3600).toISOString(), minutes(-3586).toISOString()),
                ],
                'ci-backend.yml': [
                    failureRun('Backend CI', 'recent', minutes(-21).toISOString(), minutes(6).toISOString()),
                    failureRun('Backend CI', 'stale', minutes(-3590).toISOString(), minutes(-3576).toISOString()),
                ],
            },
            { commits: pushAt(minutes(8).toISOString()) }
        )
        const { slack, outputs } = await run(github, { now, env: { GATING_WORKFLOWS: 'ci-rust.yml,ci-backend.yml' } })

        assert.equal(outputs.action, 'create') // detection unchanged: full-span byDuration still opens
        const anchor = slack.postMessage.calls[0][0]
        const body = JSON.stringify(anchor.attachments)
        assert.match(body, /Rust CI/)
        assert.match(body, /Backend CI/)
        assert.doesNotMatch(body, /\d{2,}h/) // no stale multi-day duration survives
        assert.match(anchor.text, /\(\d+m\)/) // summary duration is minutes of recent contiguous red
        // anchored to the recent failure, not the stale run
        assert.equal(anchor.metadata.event_payload.since, minutes(-21).toISOString())
    })

    it('does not falsely resolve an open incident while the newest run is still failing (regression)', async () => {
        // Newest run still failing, prior failure >180m back — detection uses the full span, so the
        // incident must stay open (never a false "master recovered").
        const now = minutes(13)
        const github = createGithubMock({
            'ci-backend.yml': [
                failureRun('Backend CI', 'recent', minutes(-10).toISOString(), minutes(5).toISOString()),
                failureRun('Backend CI', 'stale', minutes(-3600).toISOString(), minutes(-3586).toISOString()),
            ],
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { slack, outputs } = await run(github, { now, history: [activeAnchor()] })
        assert.equal(outputs.action, 'update') // stays open — not 'resolve'
        assert.equal(slack.update.calls[0][0].attachments[0].color, '#E01E5A')
        assert.equal(slack.update.calls[0][0].metadata.event_payload.status, 'active')
    })

    it('still pages for a sparse workflow whose genuine failures are far apart (regression)', async () => {
        // Sparse workflow: two genuine failures >180m apart, no green between. Must still open.
        const now = minutes(13)
        const github = createGithubMock(
            {
                'ci-rust.yml': [
                    failureRun('Rust CI', 'recent', minutes(-5).toISOString(), minutes(2).toISOString()),
                    failureRun('Rust CI', 'older', minutes(-270).toISOString(), minutes(-255).toISOString()),
                ],
                'ci-frontend.yml': runs('Frontend CI', ['success']),
            },
            { commits: pushAt(minutes(8).toISOString()) }
        )
        const { slack, outputs } = await run(github, { now, env: { GATING_WORKFLOWS: 'ci-rust.yml,ci-frontend.yml' } })
        assert.equal(outputs.action, 'create') // old gap-break would have missed this entirely
        const body = JSON.stringify(slack.postMessage.calls[0][0].attachments)
        assert.match(body, /red for \d+m/) // shows the recent contiguous red, not the ~4.5h span
        assert.doesNotMatch(body, /red for \d+h/)
    })

    it('re-running a run inside the streak does not collapse the shown duration to ~0', async () => {
        // Oldest failure re-run (updated_at bumped to ~now) — created_at anchor keeps the full span.
        const now = minutes(13)
        const f = (key, created, updated) => failureRun('Backend CI', key, created, updated)
        const github = createGithubMock({
            'ci-backend.yml': [
                f('f5', minutes(0).toISOString(), minutes(7).toISOString()),
                f('f4', minutes(-5).toISOString(), minutes(2).toISOString()),
                f('f3', minutes(-10).toISOString(), minutes(-3).toISOString()),
                f('f2', minutes(-15).toISOString(), minutes(-8).toISOString()),
                f('f1', minutes(-20).toISOString(), minutes(11).toISOString()), // oldest, re-run → updated bumped
            ],
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { slack, outputs } = await run(github, { now })
        assert.equal(outputs.action, 'create')
        const body = JSON.stringify(slack.postMessage.calls[0][0].attachments)
        assert.match(body, /5 failed runs in a row/)
        assert.match(body, /red for 33m/) // from f1's created_at, not its re-run updated_at
    })

    it('reports the honest full duration for a genuinely-continuous outage', async () => {
        // Dense failures, no gap > 180m — the cap must NOT fire, so the full ~1h13m is reported.
        const now = minutes(13)
        const f = (key, created, updated) => failureRun('Backend CI', key, created, updated)
        const github = createGithubMock(
            {
                'ci-backend.yml': [
                    f('c3', minutes(-5).toISOString(), minutes(5).toISOString()),
                    f('c2', minutes(-30).toISOString(), minutes(-20).toISOString()),
                    f('c1', minutes(-60).toISOString(), minutes(-50).toISOString()),
                ],
                'ci-frontend.yml': runs('Frontend CI', ['success']),
            },
            { commits: pushAt(minutes(8).toISOString()) }
        )
        const { slack, outputs } = await run(github, { now })
        assert.equal(outputs.action, 'create')
        const body = JSON.stringify(slack.postMessage.calls[0][0].attachments)
        assert.match(body, /red for 1h 13m/)
    })

    // --- Stale / non-terminal fetch (the 70h phantom-flap root cause) ---

    it('does not open a phantom incident when the status=completed index serves a stale page (regression)', async () => {
        // Reproduces the observed GitHub quirk behind the "opened + resolved in 4 minutes, red 70h"
        // flap: the status=completed index intermittently returns a page anchored days back (its
        // newest run an ancient failure), while master is actually green. The fix reads the fresh
        // (unfiltered) index, so a stale filtered page must never reach detection.
        const freshGreen = runs('Backend CI', ['success', 'success', 'success'])
        const github = {
            rest: {
                actions: {
                    // Serve the stale page ONLY to a status=completed request — exactly the API's behavior.
                    listWorkflowRuns: ({ workflow_id, status }) => {
                        const table = {
                            'ci-backend.yml': status === 'completed' ? stalePage() : freshGreen,
                            'ci-frontend.yml': runs('Frontend CI', ['success']),
                        }
                        return Promise.resolve({ data: { workflow_runs: table[workflow_id] || [] } })
                    },
                },
                repos: { listCommits: () => Promise.resolve({ data: pushAt(minutes(-3).toISOString()) }) },
            },
        }
        const { slack, outputs } = await run(github)
        assert.equal(outputs.action, 'none') // fresh index shows green → no incident
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls.length, 0)
    })

    it('fetchWorkflowRuns reads the fresh index and drops non-terminal runs (regression)', async () => {
        const page = [
            nonTerminalRun('ip'),
            nonTerminalRun('q', 'queued'),
            failureRun('Backend CI', 'f', minutes(-5).toISOString(), minutes(-5).toISOString()),
            { ...failureRun('Backend CI', 'x', minutes(-10).toISOString(), minutes(-10).toISOString()), conclusion: 'cancelled' },
            runs('Backend CI', ['success'])[0],
        ]
        let capturedParams
        const github = {
            rest: {
                actions: {
                    listWorkflowRuns: (params) => {
                        capturedParams = params
                        return Promise.resolve({ data: { workflow_runs: page } })
                    },
                },
            },
        }
        const result = await ciAlertsDevex.fetchWorkflowRuns(github, 'PostHog', 'posthog', 'ci-backend.yml', 40)
        // The root-cause guard: never request the eventually-consistent status=completed index.
        assert.equal(capturedParams.status, undefined)
        // in_progress/queued/cancelled dropped; settled runs kept, newest-first order preserved.
        assert.deepEqual(
            result.map((r) => r.conclusion),
            ['failure', 'success']
        )
    })

    it('pages past a head full of non-terminal runs to reach real failures (regression)', async () => {
        // A push burst leaves the newest page full of in-progress runs; per_page truncates the raw page
        // before the client-side status filter, so the completed failures sit on a later page. The
        // alerter must page to them rather than silently miss the incident (the inverse of the flap).
        const inProgress = (n) => Array.from({ length: n }, (_, i) => nonTerminalRun(`ip_${i}`))
        const failures = runs('Backend CI', Array(5).fill('failure'))
        const github = {
            rest: {
                actions: {
                    listWorkflowRuns: ({ workflow_id, per_page, page }) => {
                        if (workflow_id !== 'ci-backend.yml') {
                            return Promise.resolve({ data: { workflow_runs: runs('Frontend CI', ['success']) } })
                        }
                        // First page fills the whole page with in-progress (forcing a second fetch); page 2
                        // carries the genuine completed failures the raw page-1 truncation hid. A single-page
                        // fetch (page undefined) only ever sees the in-progress head, so it must miss the incident.
                        return Promise.resolve({ data: { workflow_runs: page >= 2 ? failures : inProgress(per_page) } })
                    },
                },
                repos: { listCommits: () => Promise.resolve({ data: pushAt(minutes(-3).toISOString()) }) },
            },
        }
        const { outputs } = await run(github)
        assert.equal(outputs.action, 'create')
        assert.equal(outputs.blocking_count, '1')
    })

    it('an in-progress run at the head does not mask a real failure streak (regression)', async () => {
        // A just-started run sits atop the fresh page; the 5 completed failures beneath it must still
        // page. Since we now fetch non-terminal runs (no server-side status filter), dropping them
        // client-side — rather than letting the head short-circuit the streak walk — is what holds.
        const github = createGithubMock({
            'ci-backend.yml': [nonTerminalRun('ip'), ...runs('Backend CI', Array(5).fill('failure'))],
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { outputs } = await run(github)
        assert.equal(outputs.action, 'create')
        assert.equal(outputs.blocking_count, '1')
    })

    // --- Stale pages on the branch/event-filtered index (the 141h phantom root cause) ---

    // A github mock whose ci-backend runs read misbehaves (`backendResponse` thunk) while
    // ci-frontend and commits stay healthy — the fixture for every unreadable-data case.
    const brokenBackendGithub = (backendResponse, onBackendRead = () => {}) => ({
        rest: {
            actions: {
                listWorkflowRuns: ({ workflow_id }) => {
                    if (workflow_id !== 'ci-backend.yml') {
                        return Promise.resolve({ data: { workflow_runs: runs('Frontend CI', ['success']) } })
                    }
                    onBackendRead()
                    return backendResponse()
                },
            },
            repos: { listCommits: () => Promise.resolve({ data: pushAt(minutes(-3).toISOString()) }) },
        },
    })

    it('a stale runs page anchored days back cannot open a phantom incident (regression)', async () => {
        // Even without status=completed, the branch/event-filtered index intermittently serves a
        // page anchored days back ("red 141h 45m", pinned to the same ancient run as the earlier
        // 70h phantom). Master's newest commit is minutes old, so the page provably trails
        // reality: retry, then treat the workflow as unreadable — never as failing.
        let backendReads = 0
        const github = brokenBackendGithub(
            () => Promise.resolve({ data: { workflow_runs: stalePage() } }),
            () => backendReads++
        )
        const { slack, outputs } = await run(github)
        assert.equal(backendReads, 3) // initial read + 2 retries before declaring the page unreadable
        assert.equal(outputs.action, 'none')
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls.length, 0)
    })

    // Unreadable data — an ancient page, an empty page, or a fetch error — must hold an open
    // incident, never read as "no failures" and strike through the anchor with a phantom recovery.
    for (const [scenario, backendResponse] of [
        ['a stale runs page', () => Promise.resolve({ data: { workflow_runs: stalePage('success') } })],
        ['an empty runs page', () => Promise.resolve({ data: { workflow_runs: [] } })],
        ['a failed runs fetch', () => Promise.reject(new Error('boom'))],
    ]) {
        it(`${scenario} cannot resolve an open incident (regression)`, async () => {
            const { slack, outputs } = await run(brokenBackendGithub(backendResponse), {
                history: [activeAnchor()],
            })
            assert.equal(outputs.action, 'hold')
            assert.equal(slack.update.calls.length, 0)
            assert.equal(slack.postMessage.calls.length, 0)
        })
    }

    it('a failed commits fetch cannot open a phantom incident via the streak-count arm (regression)', async () => {
        // Without the commits anchor no runs page is verifiable — a stale 5-failure page must not
        // open through byCount (which is not gated on recent activity).
        const github = {
            rest: {
                actions: {
                    listWorkflowRuns: ({ workflow_id }) => {
                        const table = {
                            'ci-backend.yml': runs('Backend CI', Array(5).fill('failure')),
                            'ci-frontend.yml': runs('Frontend CI', ['success']),
                        }
                        return Promise.resolve({ data: { workflow_runs: table[workflow_id] || [] } })
                    },
                },
                repos: { listCommits: () => Promise.reject(new Error('boom')) },
            },
        }
        const { slack, outputs } = await run(github)
        assert.equal(outputs.action, 'none')
        assert.equal(slack.postMessage.calls.length, 0)
        assert.equal(slack.update.calls.length, 0)
    })

    it('activity gate uses the committer date, not squash-merge author dates (regression)', async () => {
        // A squash merge keeps the branch's original author date (days old); the committer date is
        // the push time. A just-merged commit must count as activity for the wall-clock arm.
        const squashMerged = commitsAt(6000)
        squashMerged[0].commit.committer = { name: 'dev', date: minutes(-3).toISOString() }
        const github = createGithubMock(
            { 'ci-backend.yml': failingFor(25), 'ci-frontend.yml': runs('Frontend CI', ['success']) },
            { commits: squashMerged }
        )
        const { outputs } = await run(github)
        assert.equal(outputs.action, 'create')
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
