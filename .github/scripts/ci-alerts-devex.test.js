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

function createGithubMock(workflowResults) {
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
                                    updated_at: '2026-04-09T12:00:00Z',
                                },
                            ],
                        },
                    })
                }),
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
            'ci-backend.yml': { name: 'Backend CI', conclusion: 'failure' },
            'ci-frontend.yml': { name: 'Frontend CI', conclusion: 'success' },
        })

        const { writtenState } = await run(github, {
            state: { failing: {}, alerted: false },
            now: minutes(20),
        })

        expect(writtenState.failing['Backend CI'].since).toBe(minutes(20).toISOString())
    })
})
