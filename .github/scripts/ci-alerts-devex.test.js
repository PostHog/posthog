const fs = require('fs')

jest.mock('fs')

const ciAlertsDevex = require('./ci-alerts-devex')

const T_BASE = new Date('2026-04-09T12:00:00Z')
const minutes = (n) => new Date(T_BASE.getTime() + n * 60000)

function createMocks() {
    const outputs = {}
    const core = {
        setOutput: jest.fn((key, value) => {
            outputs[key] = value
        }),
    }
    return { core, outputs }
}

function createContext() {
    return {
        repo: { owner: 'PostHog', repo: 'posthog' },
    }
}

// Helper: build an array of run objects for a single workflow.
// conclusions are ordered most-recent-first (index 0 = latest run).
function runs(name, conclusions, { workflowFile } = {}) {
    return conclusions.map((conclusion, i) => ({
        name,
        conclusion,
        head_sha: `sha_${name}_${i}`,
        html_url: `https://github.com/runs/${name}/${i}`,
        updated_at: minutes(-(i * 5)).toISOString(),
    }))
}

function createGithubMock(
    workflowRuns,
    { rateLimitRemaining = 4500, rateLimitLimit = 5000, commits = [] } = {}
) {
    return {
        rest: {
            actions: {
                listWorkflowRuns: jest.fn(({ workflow_id }) => {
                    const wfRuns = workflowRuns[workflow_id] || []
                    return Promise.resolve({ data: { workflow_runs: wfRuns } })
                }),
            },
            rateLimit: {
                get: jest.fn(() =>
                    Promise.resolve({
                        data: {
                            resources: {
                                core: {
                                    remaining: rateLimitRemaining,
                                    limit: rateLimitLimit,
                                    reset: Math.floor(T_BASE.getTime() / 1000) + 3600,
                                },
                            },
                        },
                    })
                ),
            },
            repos: {
                listCommits: jest.fn(() => Promise.resolve({ data: commits })),
            },
        },
    }
}

// Helper: commits newest-first. conclusions is an array of workflow-file->conclusion
// maps, one per commit, where each map pins the critical workflow's result for
// that SHA. Any SHA referenced here is synthesized into the runs list too.
function commitsWithRuns(perCommitConclusions) {
    const commits = perCommitConclusions.map((_, i) => ({
        sha: `commit_sha_${i}`,
        html_url: `https://github.com/commit/commit_sha_${i}`,
        commit: { message: `commit ${i}`, author: { name: 'dev' } },
    }))
    const runsByWorkflow = {}
    perCommitConclusions.forEach((conclusionsMap, i) => {
        for (const [workflowFile, conclusion] of Object.entries(conclusionsMap)) {
            if (!runsByWorkflow[workflowFile]) runsByWorkflow[workflowFile] = []
            runsByWorkflow[workflowFile].push({
                name: workflowFile.replace('.yml', '').replace('ci-', '').replace(/^./, (c) => c.toUpperCase()) + ' CI',
                conclusion,
                head_sha: `commit_sha_${i}`,
                html_url: `https://github.com/runs/${workflowFile}/${i}`,
                updated_at: minutes(-(i * 5)).toISOString(),
            })
        }
    })
    return { commits, runsByWorkflow }
}

// Shorthand for all-passing runs (1 success each)
const allPassing = () => ({
    'ci-backend.yml': runs('Backend CI', ['success']),
    'ci-frontend.yml': runs('Frontend CI', ['success']),
})

// Shorthand: N consecutive failures followed by successes
const failingRuns = (name, failCount, successCount = 5) => {
    const conclusions = [
        ...Array(failCount).fill('failure'),
        ...Array(successCount).fill('success'),
    ]
    return runs(name, conclusions)
}

function run(github, { state = null, now = minutes(0) } = {}) {
    const { core, outputs } = createMocks()
    const context = createContext()

    const mockFs = {
        existsSync: jest.fn(() => state !== null),
        readFileSync: jest.fn(() => (state ? JSON.stringify(state) : '{}')),
        writeFileSync: jest.fn(),
    }

    process.env.WATCHED_WORKFLOWS = 'ci-backend.yml,ci-frontend.yml'
    process.env.ALERT_THRESHOLD_RUNS = '5'
    process.env.RED_COMMIT_THRESHOLD = '10'
    process.env.RATE_LIMIT_THRESHOLD_PERCENT = '10'
    process.env.CRITICAL_WORKFLOWS = 'ci-backend.yml'

    return ciAlertsDevex({ github, context, core }, { fs: mockFs, now }).then(() => ({
        outputs,
        core,
        mockFs,
        writtenState: mockFs.writeFileSync.mock.calls[0]
            ? JSON.parse(mockFs.writeFileSync.mock.calls[0][1])
            : null,
    }))
}

afterEach(() => {
    delete process.env.WATCHED_WORKFLOWS
    delete process.env.ALERT_THRESHOLD_RUNS
    delete process.env.RED_COMMIT_THRESHOLD
    delete process.env.RATE_LIMIT_THRESHOLD_PERCENT
    delete process.env.CRITICAL_WORKFLOWS
})

const alertedState = () => ({
    failing: {
        'Backend CI': {
            since: minutes(-25).toISOString(),
            sha: 'sha_Backend CI_4',
            run_url: 'https://github.com/runs/Backend CI/0',
            workflow_file: 'ci-backend.yml',
            consecutive_failures: 5,
        },
    },
    alerted: true,
    slack_ts: '123.456',
    slack_channel: 'C123',
    last_failing_list: 'Backend CI',
    last_failing_detail: '*Blocking:* <https://github.com/runs/Backend CI/0|Backend CI> (5 consecutive failures)',
})

describe('ci-alerts-devex', () => {
    it('no-op when all workflows pass', async () => {
        const github = createGithubMock(allPassing())

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('none')
        // No failures to track, no save needed
        expect(outputs.save_cache).toBe('false')
        expect(writtenState).toBeNull()
    })

    it.each(['failure', 'timed_out'])('records %s but does not alert under threshold', async (conclusion) => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', [conclusion, conclusion, 'success']),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('none')
        expect(outputs.save_cache).toBe('true')
        expect(writtenState.failing['Backend CI']).toBeDefined()
        expect(writtenState.failing['Backend CI'].consecutive_failures).toBe(2)
        expect(writtenState.alerted).toBe(false)
    })

    it('creates alert when consecutive failures reach threshold', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('create')
        expect(outputs.failing_workflows).toBe('Backend CI')
        expect(outputs.failing_count).toBe('1')
        expect(outputs.max_consecutive).toBe('5')
        expect(writtenState.alerted).toBe(true)
    })

    it('does not alert at threshold minus one', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 4),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs } = await run(github)

        expect(outputs.action).toBe('none')
    })

    it('updates Slack when failing set changes after alert', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': failingRuns('Frontend CI', 5),
        })

        const { outputs } = await run(github, { state: alertedState() })

        expect(outputs.action).toBe('update')
        expect(outputs.added_workflows).toBe('Frontend CI')
        expect(outputs.slack_ts).toBe('123.456')
    })

    it('resolves when all workflows pass after alert', async () => {
        const github = createGithubMock(allPassing())

        const { outputs, writtenState } = await run(github, {
            state: alertedState(),
            now: minutes(45),
        })

        expect(outputs.action).toBe('resolve')
        expect(outputs.max_consecutive).toBe('5')
        expect(outputs.duration_mins).toBeDefined()
        expect(writtenState.resolved).toBe(true)
    })

    it('resolve outputs include previous failing detail', async () => {
        const github = createGithubMock(allPassing())

        const { outputs } = await run(github, { state: alertedState() })

        expect(outputs.last_failing_list).toBe('Backend CI')
        expect(outputs.last_failing_detail).toContain('Backend CI')
        expect(outputs.last_failing_detail).toContain('5 consecutive failures')
    })

    it('stays alerted when some workflows recover but others still fail', async () => {
        const state = {
            ...alertedState(),
            failing: {
                ...alertedState().failing,
                'Frontend CI': {
                    since: minutes(-10).toISOString(),
                    sha: 'sha1',
                    run_url: 'https://github.com/runs/Frontend CI/0',
                    workflow_file: 'ci-frontend.yml',
                    consecutive_failures: 5,
                },
            },
            last_failing_list: 'Backend CI, Frontend CI',
        }

        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', ['success']),
            'ci-frontend.yml': failingRuns('Frontend CI', 3),
        })

        const { outputs } = await run(github, { state })

        // Set changed (Backend recovered), so update fires, but no resolve
        expect(outputs.action).toBe('update')
        expect(outputs.removed_workflows).toBe('Backend CI')
    })

    it('filters out cancelled runs from consecutive count', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', [
                'failure',
                'cancelled',
                'failure',
                'cancelled',
                'failure',
                'failure',
                'failure',
                'success',
            ]),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs, writtenState } = await run(github)

        // After filtering cancelled: [failure, failure, failure, failure, failure, success]
        // Consecutive from front: 5
        expect(outputs.action).toBe('create')
        expect(writtenState.failing['Backend CI'].consecutive_failures).toBe(5)
    })

    it('filters out skipped runs from consecutive count', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', ['failure', 'skipped', 'failure', 'success']),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { writtenState } = await run(github)

        // After filtering skipped: [failure, failure, success] -> 2 consecutive
        expect(writtenState.failing['Backend CI'].consecutive_failures).toBe(2)
    })

    it('includes duration as supplementary context', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs } = await run(github, { now: minutes(0) })

        expect(outputs.action).toBe('create')
        expect(outputs.duration_mins).toBeDefined()
        // duration_mins is computed from oldest failure timestamp to now
        expect(parseInt(outputs.duration_mins)).toBeGreaterThanOrEqual(0)
    })

    it('saves state when failures exist below threshold', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 2),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('none')
        expect(outputs.save_cache).toBe('true')
        expect(writtenState.failing['Backend CI'].consecutive_failures).toBe(2)
    })

    it('tracks since from oldest consecutive failure', async () => {
        // 5 failures, each 5 min apart. Oldest = index 4 = minutes(-20)
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { writtenState } = await run(github)

        expect(writtenState.failing['Backend CI'].since).toBe(minutes(-20).toISOString())
    })

    it('treats all-cancelled runs as no signal', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', ['cancelled', 'cancelled', 'skipped']),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('none')
        expect(writtenState).toBeNull()
    })

    it('treats timed_out the same as failure for duration tracking', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', ['timed_out', 'timed_out', 'timed_out', 'timed_out', 'timed_out']),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('create')
        expect(outputs.max_consecutive).toBe('5')
        expect(writtenState.failing['Backend CI'].since).toBe(minutes(-20).toISOString())
    })

    it('gracefully handles old-schema state without consecutive_failures', async () => {
        // Simulate state written by previous version of the script:
        // no consecutive_failures field, no last_failing_detail.
        const legacyState = {
            failing: {
                'Backend CI': {
                    since: minutes(-30).toISOString(),
                    sha: 'old_sha',
                    run_url: 'https://github.com/runs/old',
                    workflow_file: 'ci-backend.yml',
                },
            },
            alerted: true,
            slack_ts: '123.456',
            slack_channel: 'C123',
            last_failing_list: 'Backend CI',
        }

        const github = createGithubMock(allPassing())

        const { outputs } = await run(github, { state: legacyState, now: minutes(5) })

        expect(outputs.action).toBe('resolve')
        expect(outputs.max_consecutive).toBe('0') // unknown from legacy state, defaults to 0
        expect(outputs.last_failing_list).toBe('Backend CI')
        expect(outputs.last_failing_detail).toBe('') // legacy state has no detail
    })

    describe('rate limit checks', () => {
        it('no-op when rate limit is healthy', async () => {
            const github = createGithubMock(allPassing(), { rateLimitRemaining: 4500, rateLimitLimit: 5000 })

            const { outputs } = await run(github)

            expect(outputs.rate_limit_action).toBe('none')
            expect(outputs.rate_limit_remaining).toBe('4500')
            expect(outputs.rate_limit_limit).toBe('5000')
        })

        it('creates rate limit alert when remaining is below threshold', async () => {
            const github = createGithubMock(allPassing(), { rateLimitRemaining: 50, rateLimitLimit: 5000 })

            const { outputs, writtenState } = await run(github)

            expect(outputs.rate_limit_action).toBe('create')
            expect(outputs.rate_limit_remaining).toBe('50')
            expect(writtenState.rate_limit_alerted).toBe(true)
        })

        it('does not re-alert when already alerted for rate limit', async () => {
            const github = createGithubMock(allPassing(), { rateLimitRemaining: 30, rateLimitLimit: 5000 })

            const { outputs } = await run(github, {
                state: { failing: {}, alerted: false, rate_limit_alerted: true },
            })

            expect(outputs.rate_limit_action).toBe('none')
        })

        it('resolves rate limit alert when quota recovers', async () => {
            const github = createGithubMock(allPassing(), { rateLimitRemaining: 4500, rateLimitLimit: 5000 })

            const { outputs, writtenState } = await run(github, {
                state: {
                    failing: {},
                    alerted: false,
                    rate_limit_alerted: true,
                    rate_limit_slack_ts: '789.012',
                    rate_limit_slack_channel: 'C456',
                },
            })

            expect(outputs.rate_limit_action).toBe('resolve')
            expect(outputs.rate_limit_slack_ts).toBe('789.012')
            expect(outputs.rate_limit_slack_channel).toBe('C456')
            expect(writtenState.rate_limit_alerted).toBe(false)
        })

        it('preserves rate limit state across incident resolution', async () => {
            const github = createGithubMock(allPassing(), { rateLimitRemaining: 30, rateLimitLimit: 5000 })

            const { outputs } = await run(github, {
                state: {
                    resolved: true,
                    rate_limit_alerted: true,
                    rate_limit_slack_ts: '789.012',
                    rate_limit_slack_channel: 'C456',
                },
            })

            expect(outputs.rate_limit_action).toBe('none')
        })

        it('continues workflow checks even when rate limit is critical', async () => {
            const github = createGithubMock(
                {
                    'ci-backend.yml': failingRuns('Backend CI', 5),
                    'ci-frontend.yml': runs('Frontend CI', ['success']),
                },
                { rateLimitRemaining: 10, rateLimitLimit: 5000 }
            )

            const { outputs, writtenState } = await run(github)

            expect(outputs.action).toBe('create')
            expect(outputs.rate_limit_action).toBe('create')
            expect(writtenState.alerted).toBe(true)
            expect(writtenState.rate_limit_alerted).toBe(true)
        })

        it('degrades gracefully when rate limit API fails', async () => {
            const github = createGithubMock(allPassing())
            github.rest.rateLimit.get = jest.fn(() => Promise.reject(new Error('API error')))

            const { outputs } = await run(github)

            expect(outputs.rate_limit_action).toBe('none')
            expect(outputs.rate_limit_remaining).toBeUndefined()
            expect(outputs.action).toBe('none')
        })
    })

    describe('severity differentiation', () => {
        it('labels critical-only failures correctly', async () => {
            const github = createGithubMock({
                'ci-backend.yml': failingRuns('Backend CI', 5),
                'ci-frontend.yml': runs('Frontend CI', ['success']),
            })

            const { outputs } = await run(github)

            expect(outputs.action).toBe('create')
            expect(outputs.failing_detail).toMatch(/\*Blocking:\*.*Backend CI.*5 consecutive failures/)
            expect(outputs.failing_detail).not.toContain('Non-blocking')
        })

        it('labels non-critical-only failures correctly', async () => {
            const github = createGithubMock({
                'ci-backend.yml': runs('Backend CI', ['success']),
                'ci-frontend.yml': failingRuns('Frontend CI', 5),
            })

            const { outputs } = await run(github)

            expect(outputs.action).toBe('create')
            expect(outputs.failing_detail).toMatch(/\*Non-blocking:\*.*Frontend CI.*5 consecutive failures/)
            expect(outputs.failing_detail).not.toContain('Blocking:')
        })

        it('splits mixed failures into critical and other', async () => {
            const github = createGithubMock({
                'ci-backend.yml': failingRuns('Backend CI', 5),
                'ci-frontend.yml': failingRuns('Frontend CI', 5),
            })

            const { outputs } = await run(github)

            expect(outputs.action).toBe('create')
            expect(outputs.failing_detail).toMatch(/^\*Blocking:\*.*Backend CI/)
            expect(outputs.failing_detail).toMatch(/\*Non-blocking:\*.*Frontend CI/)
        })

        it('stores workflow_file and consecutive_failures in failing map', async () => {
            const github = createGithubMock({
                'ci-backend.yml': failingRuns('Backend CI', 3),
                'ci-frontend.yml': runs('Frontend CI', ['success']),
            })

            const { writtenState } = await run(github)

            expect(writtenState.failing['Backend CI'].workflow_file).toBe('ci-backend.yml')
            expect(writtenState.failing['Backend CI'].consecutive_failures).toBe(3)
        })
    })

    describe('red commit streak', () => {
        // Only ci-backend.yml is critical in the test env; ci-frontend.yml is not.
        // Red classification therefore depends solely on ci-backend outcomes per SHA.

        const greenCommits = (n) => commitsWithRuns(Array(n).fill({ 'ci-backend.yml': 'success' }))
        const redCommits = (n) => commitsWithRuns(Array(n).fill({ 'ci-backend.yml': 'failure' }))

        it('no-op when all recent commits are green', async () => {
            const { commits, runsByWorkflow } = greenCommits(12)
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github)

            expect(outputs.red_commits_action).toBe('none')
            expect(outputs.red_commits_count).toBe('0')
        })

        it('does not alert at threshold minus one', async () => {
            const { commits, runsByWorkflow } = redCommits(9)
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github)

            expect(outputs.red_commits_action).toBe('none')
            expect(outputs.red_commits_count).toBe('9')
        })

        it('creates alert at 10 consecutive red commits', async () => {
            const { commits, runsByWorkflow } = redCommits(10)
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs, writtenState } = await run(github)

            expect(outputs.red_commits_action).toBe('create')
            expect(outputs.red_commits_count).toBe('10')
            expect(outputs.red_commits_detail).toContain('commit_sha_0'.slice(0, 7))
            expect(writtenState.red_commits_alerted).toBe(true)
            expect(writtenState.red_commits_last_count).toBe(10)
        })

        it('attributes culprits per commit in detail', async () => {
            // ci-backend is critical, so only its failures mark commits red.
            // Mix: half fail with backend, half fail with backend (only critical one in env).
            const { commits, runsByWorkflow } = commitsWithRuns([
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'timed_out' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
                { 'ci-backend.yml': 'failure' },
            ])
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github)

            expect(outputs.red_commits_action).toBe('create')
            expect(outputs.red_commits_detail.split('\n')).toHaveLength(10)
            expect(outputs.red_commits_detail).toMatch(/Backend CI/)
        })

        it('green commit breaks the streak', async () => {
            // newest 8 red, then a green, then more red — streak is only 8
            const { commits, runsByWorkflow } = commitsWithRuns([
                ...Array(8).fill({ 'ci-backend.yml': 'failure' }),
                { 'ci-backend.yml': 'success' },
                ...Array(5).fill({ 'ci-backend.yml': 'failure' }),
            ])
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github)

            expect(outputs.red_commits_count).toBe('8')
            expect(outputs.red_commits_action).toBe('none')
        })

        it('unknown commits do not count but do not break', async () => {
            // newest 3 have no critical runs (unknown), next 10 are red
            const { commits, runsByWorkflow } = commitsWithRuns([
                {},
                {},
                {},
                ...Array(10).fill({ 'ci-backend.yml': 'failure' }),
            ])
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github)

            expect(outputs.red_commits_count).toBe('10')
            expect(outputs.red_commits_action).toBe('create')
        })

        it('non-critical workflow failures do not mark a commit red', async () => {
            // ci-frontend is not critical — its failures should be ignored.
            // Every commit passes ci-backend but fails ci-frontend.
            const { commits, runsByWorkflow } = commitsWithRuns(
                Array(10).fill({ 'ci-backend.yml': 'success', 'ci-frontend.yml': 'failure' })
            )
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github)

            expect(outputs.red_commits_count).toBe('0')
            expect(outputs.red_commits_action).toBe('none')
        })

        it('updates Slack when streak grows after alert', async () => {
            const { commits, runsByWorkflow } = redCommits(14)
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github, {
                state: {
                    failing: {},
                    red_commits_alerted: true,
                    red_commits_slack_ts: '999.999',
                    red_commits_slack_channel: 'Cred',
                    red_commits_last_count: 10,
                },
            })

            expect(outputs.red_commits_action).toBe('update')
            expect(outputs.red_commits_count).toBe('14')
            expect(outputs.red_commits_slack_ts).toBe('999.999')
        })

        it('does not re-update when count is unchanged', async () => {
            const { commits, runsByWorkflow } = redCommits(10)
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs } = await run(github, {
                state: {
                    failing: {},
                    red_commits_alerted: true,
                    red_commits_slack_ts: '999.999',
                    red_commits_slack_channel: 'Cred',
                    red_commits_last_count: 10,
                },
            })

            expect(outputs.red_commits_action).toBe('none')
        })

        it('resolves when streak drops below threshold', async () => {
            const { commits, runsByWorkflow } = greenCommits(12)
            const github = createGithubMock(runsByWorkflow, { commits })

            const { outputs, writtenState } = await run(github, {
                state: {
                    failing: {},
                    red_commits_alerted: true,
                    red_commits_slack_ts: '999.999',
                    red_commits_slack_channel: 'Cred',
                    red_commits_last_count: 12,
                    red_commits_last_sample: '• abc1234 — Backend CI',
                },
            })

            expect(outputs.red_commits_action).toBe('resolve')
            expect(outputs.red_commits_last_count).toBe('12')
            expect(outputs.red_commits_slack_ts).toBe('999.999')
            expect(writtenState.red_commits_alerted).toBe(false)
            expect(writtenState.red_commits_last_count).toBe(0)
        })

        it('old-schema state without red_commits fields degrades gracefully', async () => {
            const { commits, runsByWorkflow } = greenCommits(12)
            const github = createGithubMock(runsByWorkflow, { commits })

            const legacyState = {
                failing: {},
                alerted: false,
                // no red_commits_* fields
            }

            const { outputs } = await run(github, { state: legacyState })

            expect(outputs.red_commits_action).toBe('none')
            expect(outputs.red_commits_count).toBe('0')
        })

        it('degrades gracefully when listCommits fails', async () => {
            const github = createGithubMock(allPassing())
            github.rest.repos.listCommits = jest.fn(() => Promise.reject(new Error('API error')))

            const { outputs } = await run(github)

            expect(outputs.red_commits_action).toBe('none')
            expect(outputs.red_commits_count).toBe('0')
        })
    })
})
