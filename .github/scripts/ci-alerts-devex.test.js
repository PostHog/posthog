const fs = require('fs')

jest.mock('fs')

const ciAlertsDevex = require('./ci-alerts-devex')

const T_BASE = new Date('2026-04-09T12:00:00Z')
const minutes = (n) => new Date(T_BASE.getTime() + n * 60000)

// Helper: array of workflow-run objects. conclusions newest-first.
function runs(name, conclusions) {
    return conclusions.map((conclusion, i) => ({
        name,
        conclusion,
        head_sha: `sha_${name}_${i}`,
        html_url: `https://github.com/runs/${name}/${i}`,
        updated_at: minutes(-(i * 5)).toISOString(),
    }))
}

// Helper: N failures followed by 5 successes.
const failingRuns = (name, failCount) =>
    runs(name, [...Array(failCount).fill('failure'), ...Array(5).fill('success')])

const allPassing = () => ({
    'ci-backend.yml': runs('Backend CI', ['success']),
    'ci-frontend.yml': runs('Frontend CI', ['success']),
})

// Helper: build listCommits + listWorkflowRuns mocks aligned by SHA.
// Each element of perCommitConclusions is a {workflowFile: conclusion} map
// for one commit (newest first).
function commitsWithRuns(perCommitConclusions) {
    const commits = perCommitConclusions.map((_, i) => ({
        sha: `commit_sha_${i}`,
        html_url: `https://github.com/commit/commit_sha_${i}`,
        commit: { message: `commit ${i}`, author: { name: 'dev' } },
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

function createGithubMock(workflowRuns, { rateLimitRemaining = 4500, commits = [] } = {}) {
    return {
        rest: {
            actions: {
                listWorkflowRuns: jest.fn(({ workflow_id }) =>
                    Promise.resolve({ data: { workflow_runs: workflowRuns[workflow_id] || [] } })
                ),
            },
            rateLimit: {
                get: jest.fn(() =>
                    Promise.resolve({
                        data: {
                            resources: {
                                core: {
                                    remaining: rateLimitRemaining,
                                    limit: 5000,
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

function run(github, { state = null, now = minutes(0) } = {}) {
    const outputs = {}
    const core = { setOutput: jest.fn((k, v) => (outputs[k] = v)) }
    const mockFs = {
        existsSync: jest.fn(() => state !== null),
        readFileSync: jest.fn(() => (state ? JSON.stringify(state) : '{}')),
        writeFileSync: jest.fn(),
    }

    process.env.WATCHED_WORKFLOWS = 'ci-backend.yml,ci-frontend.yml'
    process.env.WORKFLOW_FAILURE_STREAK_THRESHOLD = '5'
    process.env.COMMIT_FAILURE_STREAK_THRESHOLD = '10'
    process.env.RATE_LIMIT_THRESHOLD_PERCENT = '10'
    process.env.CRITICAL_WORKFLOWS = 'ci-backend.yml'

    return ciAlertsDevex({ github, context: { repo: { owner: 'PostHog', repo: 'posthog' } }, core }, { fs: mockFs, now }).then(() => ({
        outputs,
        writtenState: mockFs.writeFileSync.mock.calls[0]
            ? JSON.parse(mockFs.writeFileSync.mock.calls[0][1])
            : null,
    }))
}

afterEach(() => {
    delete process.env.WATCHED_WORKFLOWS
    delete process.env.WORKFLOW_FAILURE_STREAK_THRESHOLD
    delete process.env.COMMIT_FAILURE_STREAK_THRESHOLD
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
        const { outputs, writtenState } = await run(createGithubMock(allPassing()))
        expect(outputs.action).toBe('none')
        expect(writtenState).toBeNull()
    })

    it.each(['failure', 'timed_out'])('creates alert on 5 consecutive %s', async (conclusion) => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', Array(5).fill(conclusion)),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { outputs, writtenState } = await run(github)
        expect(outputs.action).toBe('create')
        expect(outputs.max_consecutive).toBe('5')
        expect(outputs.failing_detail).toMatch(/\*Blocking:\*.*Backend CI/)
        expect(writtenState.alerted).toBe(true)
    })

    it('updates Slack when failing set changes after alert', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': failingRuns('Frontend CI', 5),
        })
        const { outputs } = await run(github, { state: alertedState() })
        expect(outputs.action).toBe('update')
        expect(outputs.added_workflows).toBe('Frontend CI')
    })

    it('resolves and preserves failing detail', async () => {
        const { outputs, writtenState } = await run(createGithubMock(allPassing()), { state: alertedState() })
        expect(outputs.action).toBe('resolve')
        expect(outputs.last_failing_detail).toContain('Backend CI')
        expect(writtenState.resolved).toBe(true)
    })

    it('filters cancelled and skipped runs from consecutive count', async () => {
        const github = createGithubMock({
            'ci-backend.yml': runs('Backend CI', ['failure', 'cancelled', 'failure', 'skipped', 'failure', 'failure', 'failure', 'success']),
            'ci-frontend.yml': runs('Frontend CI', ['success']),
        })
        const { outputs } = await run(github)
        expect(outputs.action).toBe('create')
        expect(outputs.max_consecutive).toBe('5')
    })

    it('splits critical vs non-critical failures in detail', async () => {
        const github = createGithubMock({
            'ci-backend.yml': failingRuns('Backend CI', 5),
            'ci-frontend.yml': failingRuns('Frontend CI', 5),
        })
        const { outputs } = await run(github)
        expect(outputs.failing_detail).toMatch(/^\*Blocking:\*.*Backend CI/)
        expect(outputs.failing_detail).toMatch(/\*Non-blocking:\*.*Frontend CI/)
    })

    describe('rate limit', () => {
        it('alerts when critical, resolves when healthy', async () => {
            // Fire alert
            let github = createGithubMock(allPassing(), { rateLimitRemaining: 50 })
            let { outputs, writtenState } = await run(github)
            expect(outputs.rate_limit_action).toBe('create')
            expect(writtenState.rate_limit_alerted).toBe(true)

            // Recover
            github = createGithubMock(allPassing(), { rateLimitRemaining: 4500 })
            ;({ outputs, writtenState } = await run(github, {
                state: { failing: {}, rate_limit_alerted: true, rate_limit_slack_ts: '1', rate_limit_slack_channel: 'C' },
            }))
            expect(outputs.rate_limit_action).toBe('resolve')
            expect(writtenState.rate_limit_alerted).toBe(false)
        })

        it('degrades gracefully when rate limit API fails', async () => {
            const github = createGithubMock(allPassing())
            github.rest.rateLimit.get = jest.fn(() => Promise.reject(new Error('API error')))
            const { outputs } = await run(github)
            expect(outputs.rate_limit_action).toBe('none')
            expect(outputs.action).toBe('none')
        })

        it('fires workflow and rate-limit signals independently in the same tick', async () => {
            const github = createGithubMock(
                {
                    'ci-backend.yml': runs('Backend CI', Array(5).fill('failure')),
                    'ci-frontend.yml': runs('Frontend CI', ['success']),
                },
                { rateLimitRemaining: 50 }
            )
            const { outputs } = await run(github)
            expect(outputs.action).toBe('create')
            expect(outputs.rate_limit_action).toBe('create')
        })
    })

    describe('red commit streak', () => {
        const greenCommits = (n) => commitsWithRuns(Array(n).fill({ 'ci-backend.yml': 'success' }))
        const redCommits = (n) => commitsWithRuns(Array(n).fill({ 'ci-backend.yml': 'failure' }))

        it('no-op below threshold, creates alert at threshold', async () => {
            // 9 red → no alert
            let { commits, runsByWorkflow } = redCommits(9)
            let { outputs } = await run(createGithubMock(runsByWorkflow, { commits }))
            expect(outputs.commit_failure_streak_action).toBe('none')
            expect(outputs.commit_failure_streak_count).toBe('9')

            // 10 red → create, with detail listing culprit per commit
            ;({ commits, runsByWorkflow } = redCommits(10))
            ;({ outputs } = await run(createGithubMock(runsByWorkflow, { commits })))
            expect(outputs.commit_failure_streak_action).toBe('create')
            expect(outputs.commit_failure_streak_count).toBe('10')
            expect(outputs.commit_failure_streak_detail.split('\n')).toHaveLength(10)
            expect(outputs.commit_failure_streak_detail).toMatch(/Backend CI/)
        })

        it('unknown commits skip, non-critical failures ignored, green breaks streak', async () => {
            // newest 2 unknown, then 1 green, then 8 red → green breaks before threshold
            const { commits, runsByWorkflow } = commitsWithRuns([
                {},
                {},
                { 'ci-backend.yml': 'success' },
                ...Array(8).fill({ 'ci-backend.yml': 'failure', 'ci-frontend.yml': 'failure' }),
            ])
            const { outputs } = await run(createGithubMock(runsByWorkflow, { commits }))
            expect(outputs.commit_failure_streak_count).toBe('0')
            expect(outputs.commit_failure_streak_action).toBe('none')
        })

        it('non-critical-only failures do not mark commits red', async () => {
            const { commits, runsByWorkflow } = commitsWithRuns(
                Array(10).fill({ 'ci-backend.yml': 'success', 'ci-frontend.yml': 'failure' })
            )
            const { outputs } = await run(createGithubMock(runsByWorkflow, { commits }))
            expect(outputs.commit_failure_streak_count).toBe('0')
        })

        it('updates when streak grows, resolves when drops below threshold', async () => {
            const stateAlerted = {
                failing: {},
                commit_failure_streak_alerted: true,
                commit_failure_streak_slack_ts: '999.999',
                commit_failure_streak_slack_channel: 'Cred',
                commit_failure_streak_last_count: 10,
            }

            // 14 red after alerted-at-10 → update
            let { commits, runsByWorkflow } = redCommits(14)
            let { outputs } = await run(createGithubMock(runsByWorkflow, { commits }), { state: stateAlerted })
            expect(outputs.commit_failure_streak_action).toBe('update')
            expect(outputs.commit_failure_streak_count).toBe('14')

            // 10 red with last_count already 10 → no-op (idempotent at/over threshold, no growth)
            ;({ commits, runsByWorkflow } = redCommits(10))
            ;({ outputs } = await run(createGithubMock(runsByWorkflow, { commits }), { state: stateAlerted }))
            expect(outputs.commit_failure_streak_action).toBe('none')
            expect(outputs.commit_failure_streak_count).toBe('10')

            // All green after alerted → resolve
            ;({ commits, runsByWorkflow } = greenCommits(12))
            let writtenState
            ;({ outputs, writtenState } = await run(createGithubMock(runsByWorkflow, { commits }), { state: stateAlerted }))
            expect(outputs.commit_failure_streak_action).toBe('resolve')
            expect(writtenState.commit_failure_streak_alerted).toBe(false)
        })
    })
})
