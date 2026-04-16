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

function createGithubMock(workflowResults, { rateLimitRemaining = 4500, rateLimitLimit = 5000 } = {}) {
    return {
        rest: {
            actions: {
                listWorkflowRuns: jest.fn(({ workflow_id }) => {
                    const result = workflowResults[workflow_id]
                    if (!result) return Promise.resolve({ data: { workflow_runs: [] } })
                    return Promise.resolve({
                        data: {
                            workflow_runs: [
                                {
                                    name: result.name,
                                    conclusion: result.conclusion,
                                    head_sha: result.sha || 'abc1234',
                                    html_url: result.run_url || `https://github.com/runs/${result.name}`,
                                    updated_at: result.updated_at || T_BASE.toISOString(),
                                },
                            ],
                        },
                    })
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
        },
    }
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
    process.env.ALERT_THRESHOLD_MINUTES = '30'
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
    delete process.env.ALERT_THRESHOLD_MINUTES
    delete process.env.RATE_LIMIT_THRESHOLD_PERCENT
    delete process.env.CRITICAL_WORKFLOWS
})

const failingState = (sinceMin = 0) => ({
    failing: {
        'Backend CI': {
            since: minutes(sinceMin).toISOString(),
            sha: 'abc1234',
            run_url: 'https://github.com/runs/1',
        },
    },
    alerted: false,
})

const alertedState = (sinceMin = 0) => ({
    ...failingState(sinceMin),
    alerted: true,
    slack_ts: '123.456',
    slack_channel: 'C123',
    last_failing_list: 'Backend CI',
})

describe('ci-alerts-devex', () => {
    it('no-op when all workflows pass', async () => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'success' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { outputs } = await run(github)

        expect(outputs.action).toBe('none')
        expect(outputs.save_cache).toBe('true')
    })

    it.each(['failure', 'timed_out'])('records %s but does not alert under threshold', async (conclusion) => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { outputs, writtenState } = await run(github)

        expect(outputs.action).toBe('none')
        expect(outputs.save_cache).toBe('true')
        expect(writtenState.failing['Backend CI']).toBeDefined()
        expect(writtenState.alerted).toBe(false)
    })

    it('creates alert when failure persists past threshold', async () => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { outputs, writtenState } = await run(github, {
            state: failingState(0),
            now: minutes(31),
        })

        expect(outputs.action).toBe('create')
        expect(outputs.failing_workflows).toBe('Backend CI')
        expect(outputs.failing_count).toBe('1')
        expect(outputs.duration_mins).toBe('31')
        expect(writtenState.alerted).toBe(true)
    })

    it('updates Slack when failing set changes after alert', async () => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'failure' },
        })

        const { outputs } = await run(github, { state: alertedState(0), now: minutes(35) })

        expect(outputs.action).toBe('update')
        expect(outputs.added_workflows).toBe('Frontend CI')
        expect(outputs.slack_ts).toBe('123.456')
    })

    it('resolves when all workflows pass after alert', async () => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'success' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { outputs, writtenState } = await run(github, {
            state: alertedState(0),
            now: minutes(45),
        })

        expect(outputs.action).toBe('resolve')
        expect(outputs.duration_mins).toBe('45')
        expect(writtenState.resolved).toBe(true)
    })

    it('silently clears when flake self-heals before threshold', async () => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'success' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { outputs } = await run(github, { state: failingState(0), now: minutes(10) })

        expect(outputs.action).toBe('none')
        expect(outputs.save_cache).toBe('true')
    })

    it('resets the clock when a workflow recovers then fails again', async () => {
        const github = createGithubMock({
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure', updated_at: minutes(18).toISOString() },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { writtenState } = await run(github, {
            state: { failing: {}, alerted: false },
            now: minutes(20),
        })

        // since uses the run's updated_at, not observation time
        expect(writtenState.failing['Backend CI'].since).toBe(minutes(18).toISOString())
    })

    describe('rate limit checks', () => {
        const allPassing = {
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'success' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        }

        it('no-op when rate limit is healthy', async () => {
            const github = createGithubMock(allPassing, { rateLimitRemaining: 4500, rateLimitLimit: 5000 })

            const { outputs } = await run(github)

            expect(outputs.rate_limit_action).toBe('none')
            expect(outputs.rate_limit_remaining).toBe('4500')
            expect(outputs.rate_limit_limit).toBe('5000')
        })

        it('creates rate limit alert when remaining is below threshold', async () => {
            const github = createGithubMock(allPassing, { rateLimitRemaining: 50, rateLimitLimit: 5000 })

            const { outputs, writtenState } = await run(github)

            expect(outputs.rate_limit_action).toBe('create')
            expect(outputs.rate_limit_remaining).toBe('50')
            expect(writtenState.rate_limit_alerted).toBe(true)
        })

        it('does not re-alert when already alerted for rate limit', async () => {
            const github = createGithubMock(allPassing, { rateLimitRemaining: 30, rateLimitLimit: 5000 })

            const { outputs } = await run(github, {
                state: { failing: {}, alerted: false, rate_limit_alerted: true },
            })

            expect(outputs.rate_limit_action).toBe('none')
        })

        it('resolves rate limit alert when quota recovers', async () => {
            const github = createGithubMock(allPassing, { rateLimitRemaining: 4500, rateLimitLimit: 5000 })

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
            const github = createGithubMock(
                {
                    'ci-backend.yml': { name: 'Backend CI', conclusion: 'success' },
                    'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
                },
                { rateLimitRemaining: 30, rateLimitLimit: 5000 }
            )

            const { outputs } = await run(github, {
                state: {
                    resolved: true,
                    rate_limit_alerted: true,
                    rate_limit_slack_ts: '789.012',
                    rate_limit_slack_channel: 'C456',
                },
            })

            // Should not re-create — prior alert is still tracked
            expect(outputs.rate_limit_action).toBe('none')
        })

        it('continues workflow checks even when rate limit is critical', async () => {
            const github = createGithubMock(
                {
                    'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
                    'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
                },
                { rateLimitRemaining: 10, rateLimitLimit: 5000 }
            )

            const { outputs, writtenState } = await run(github, {
                state: failingState(0),
                now: minutes(31),
            })

            // Both concerns fire independently
            expect(outputs.action).toBe('create')
            expect(outputs.rate_limit_action).toBe('create')
            expect(writtenState.alerted).toBe(true)
            expect(writtenState.rate_limit_alerted).toBe(true)
        })

        it('degrades gracefully when rate limit API fails', async () => {
            const github = createGithubMock(allPassing)
            github.rest.rateLimit.get = jest.fn(() => Promise.reject(new Error('API error')))

            const { outputs } = await run(github)

            expect(outputs.rate_limit_action).toBe('none')
            expect(outputs.rate_limit_remaining).toBeUndefined()
            expect(outputs.action).toBe('none')
        })
    })

    describe('severity differentiation', () => {
        // CRITICAL_WORKFLOWS is set to 'ci-backend.yml' in run()

        it('labels critical-only failures correctly', async () => {
            const github = createGithubMock({
                'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
                'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
            })

            const { outputs } = await run(github, { state: failingState(0), now: minutes(31) })

            expect(outputs.failing_links_blocking).toContain('Backend CI')
            expect(outputs.failing_links_non_blocking).toBe('')
            expect(outputs.failing_detail).toBe('*Blocking:* <https://github.com/runs/Backend CI|Backend CI>')
        })

        it('labels non-critical-only failures correctly', async () => {
            const github = createGithubMock({
                'ci-backend.yml': { name: 'Backend CI', conclusion: 'success' },
                'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'failure' },
            })

            const state = {
                failing: {
                    'Frontend CI': {
                        since: minutes(0).toISOString(),
                        sha: 'abc1234',
                        run_url: 'https://github.com/runs/Frontend CI',
                        workflow_file: 'ci-frontend.yml',
                    },
                },
                alerted: false,
            }

            const { outputs } = await run(github, { state, now: minutes(31) })

            expect(outputs.failing_links_blocking).toBe('')
            expect(outputs.failing_links_non_blocking).toContain('Frontend CI')
            expect(outputs.failing_detail).toBe('*Non-blocking:* <https://github.com/runs/Frontend CI|Frontend CI>')
        })

        it('splits mixed failures into critical and other', async () => {
            const github = createGithubMock({
                'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
                'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'failure' },
            })

            const state = {
                failing: {
                    'Backend CI': {
                        since: minutes(0).toISOString(),
                        sha: 'abc1234',
                        run_url: 'https://github.com/runs/Backend CI',
                        workflow_file: 'ci-backend.yml',
                    },
                    'Frontend CI': {
                        since: minutes(0).toISOString(),
                        sha: 'abc1234',
                        run_url: 'https://github.com/runs/Frontend CI',
                        workflow_file: 'ci-frontend.yml',
                    },
                },
                alerted: false,
            }

            const { outputs } = await run(github, { state, now: minutes(31) })

            expect(outputs.failing_links_blocking).toContain('Backend CI')
            expect(outputs.failing_links_non_blocking).toContain('Frontend CI')
            expect(outputs.failing_detail).toMatch(/^\*Blocking:\*.*Backend CI.*\n\*Non-blocking:\*.*Frontend CI/)
        })

        it('stores workflow_file in failing map', async () => {
            const github = createGithubMock({
                'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
                'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
            })

            const { writtenState } = await run(github)

            expect(writtenState.failing['Backend CI'].workflow_file).toBe('ci-backend.yml')
        })
    })
})
