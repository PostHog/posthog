const monitor = require('./monitor-github-rate-limit')

const T_BASE = new Date('2026-04-27T18:00:00Z')
const T_BASE_SECONDS = Math.floor(T_BASE.getTime() / 1000)

function snapshot({ remaining, limit, used, resetSecondsFromBase = 1800 }) {
    return {
        remaining,
        limit,
        used: used ?? limit - remaining,
        reset: T_BASE_SECONDS + resetSecondsFromBase,
    }
}

function createGithubMock(resources) {
    return {
        rest: {
            rateLimit: {
                get: jest.fn(() => Promise.resolve({ data: { resources } })),
            },
        },
    }
}

function createCore() {
    return {
        info: jest.fn(),
        warning: jest.fn(),
        setOutput: jest.fn(),
    }
}

const context = { repo: { owner: 'PostHog', repo: 'posthog' } }

const fetchOk = () => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('ok') })

describe('monitor-github-rate-limit', () => {
    const ORIGINAL_ENV = process.env

    beforeEach(() => {
        process.env = { ...ORIGINAL_ENV }
        delete process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN
        delete process.env.GITHUB_RUN_ID
    })

    afterAll(() => {
        process.env = ORIGINAL_ENV
    })

    test('emits one event per resource', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        const fetchMock = jest.fn(fetchOk)
        const core = createCore()
        const github = createGithubMock({
            core: snapshot({ remaining: 12000, limit: 15000 }),
            search: snapshot({ remaining: 30, limit: 30 }),
            graphql: snapshot({ remaining: 5000, limit: 5000 }),
        })

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(fetchMock).toHaveBeenCalledTimes(3)
        expect(core.setOutput).toHaveBeenCalledWith('emitted', '3')
        expect(core.setOutput).toHaveBeenCalledWith('failures', '0')
    })

    test('skips emission when devex token is not configured', async () => {
        const fetchMock = jest.fn(fetchOk)
        const core = createCore()
        const github = createGithubMock({ core: snapshot({ remaining: 1, limit: 15000 }) })

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(fetchMock).not.toHaveBeenCalled()
        expect(core.warning).toHaveBeenCalledWith(expect.stringContaining('POSTHOG_DEVEX_PROJECT_API_TOKEN'))
        expect(core.setOutput).toHaveBeenCalledWith('emitted', '0')
    })

    test('skips malformed snapshots without crashing', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        const fetchMock = jest.fn(fetchOk)
        const core = createCore()
        const github = createGithubMock({
            core: snapshot({ remaining: 1000, limit: 15000 }),
            broken: { limit: 'whoops' },
            empty: null,
            partial: { limit: 100 }, // missing remaining
        })

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(core.setOutput).toHaveBeenCalledWith('emitted', '1')
        expect(core.setOutput).toHaveBeenCalledWith('failures', '0')
    })

    test('counts capture failures without aborting subsequent emissions', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        let calls = 0
        const fetchMock = jest.fn(() => {
            calls++
            if (calls === 1) {
                return Promise.resolve({ ok: false, status: 500, text: () => Promise.resolve('boom') })
            }
            return fetchOk()
        })
        const core = createCore()
        const github = createGithubMock({
            core: snapshot({ remaining: 12000, limit: 15000 }),
            graphql: snapshot({ remaining: 4000, limit: 5000 }),
        })

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(fetchMock).toHaveBeenCalledTimes(2)
        expect(core.setOutput).toHaveBeenCalledWith('emitted', '1')
        expect(core.setOutput).toHaveBeenCalledWith('failures', '1')
        expect(core.warning).toHaveBeenCalledWith(expect.stringContaining('capture 500'))
    })

    test('payload includes utilization, reset metadata, and run id', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        process.env.GITHUB_RUN_ID = '42'
        const captured = []
        const fetchMock = jest.fn((_url, opts) => {
            captured.push(JSON.parse(opts.body))
            return fetchOk()
        })
        const core = createCore()
        const github = createGithubMock({
            core: snapshot({ remaining: 3000, limit: 15000, resetSecondsFromBase: 600 }),
        })

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(captured).toHaveLength(1)
        const payload = captured[0]
        expect(payload).toMatchObject({
            api_key: 'devex-key',
            event: 'github_rate_limit_observed',
            distinct_id: 'PostHog/posthog',
            timestamp: T_BASE.toISOString(),
        })
        expect(payload.properties).toMatchObject({
            repo: 'PostHog/posthog',
            resource: 'core',
            used: 12000,
            remaining: 3000,
            limit: 15000,
            source: 'github_token',
            workflow_run_id: '42',
            reset_in_seconds: 600,
        })
        expect(payload.properties.utilization).toBeCloseTo(12000 / 15000)
        expect(payload.properties.reset_at).toBe(new Date((T_BASE_SECONDS + 600) * 1000).toISOString())
    })
})

describe('buildProperties', () => {
    test('falls back to limit-remaining when used is missing', () => {
        const props = monitor.buildProperties({
            resource: 'core',
            snapshot: { remaining: 4000, limit: 15000, reset: T_BASE_SECONDS + 60 },
            observedAt: T_BASE.toISOString(),
            repo: 'PostHog/posthog',
            runId: null,
        })
        expect(props.used).toBe(11000)
        expect(props.utilization).toBeCloseTo(11000 / 15000)
    })

    test('handles already-reset bucket without negative reset_in_seconds', () => {
        const props = monitor.buildProperties({
            resource: 'core',
            snapshot: { remaining: 15000, limit: 15000, used: 0, reset: T_BASE_SECONDS - 60 },
            observedAt: T_BASE.toISOString(),
            repo: 'PostHog/posthog',
            runId: null,
        })
        expect(props.reset_in_seconds).toBe(0)
    })
})
