const monitor = require('./monitor-github-rate-limit')

const T_BASE = new Date('2026-04-27T18:00:00Z')
const T_BASE_SECONDS = Math.floor(T_BASE.getTime() / 1000)

const snapshot = ({ remaining, limit, resetSecondsFromBase = 1800 }) => ({
    remaining,
    limit,
    used: limit - remaining,
    reset: T_BASE_SECONDS + resetSecondsFromBase,
})

const createGithubMock = (resources) => ({
    rest: { rateLimit: { get: jest.fn(() => Promise.resolve({ data: { resources } })) } },
})

const createCore = () => ({ info: jest.fn(), warning: jest.fn(), setOutput: jest.fn() })

const fetchOk = () => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('ok') })

const context = { repo: { owner: 'PostHog', repo: 'posthog' } }

describe('monitor-github-rate-limit', () => {
    const ORIGINAL_ENV = process.env

    beforeEach(() => {
        process.env = { ...ORIGINAL_ENV }
        delete process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN
    })

    afterAll(() => {
        process.env = ORIGINAL_ENV
    })

    test('emits one event per resource with the expected payload shape', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        const captured = []
        const fetchMock = jest.fn((_url, opts) => {
            captured.push(JSON.parse(opts.body))
            return fetchOk()
        })
        const github = createGithubMock({
            core: snapshot({ remaining: 3000, limit: 15000, resetSecondsFromBase: 600 }),
            graphql: snapshot({ remaining: 5000, limit: 5000 }),
        })
        const core = createCore()

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(captured).toHaveLength(2)
        expect(captured[0]).toMatchObject({
            api_key: 'devex-key',
            event: 'github_rate_limit_observed',
            distinct_id: 'PostHog/posthog',
            properties: {
                resource: 'core',
                used: 12000,
                remaining: 3000,
                limit: 15000,
                source: 'github_token',
                reset_in_seconds: 600,
            },
        })
        expect(captured[0].properties.utilization).toBeCloseTo(12000 / 15000)
        expect(core.setOutput).toHaveBeenCalledWith('emitted', '2')
    })

    test('counts capture failures without aborting later emissions', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        let calls = 0
        const fetchMock = jest.fn(() =>
            ++calls === 1
                ? Promise.resolve({ ok: false, status: 500, text: () => Promise.resolve('boom') })
                : fetchOk()
        )
        const github = createGithubMock({
            core: snapshot({ remaining: 3000, limit: 15000 }),
            graphql: snapshot({ remaining: 4000, limit: 5000 }),
        })
        const core = createCore()

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(core.setOutput).toHaveBeenCalledWith('emitted', '1')
        expect(core.setOutput).toHaveBeenCalledWith('failures', '1')
        expect(core.warning).toHaveBeenCalledWith(expect.stringContaining('capture 500'))
    })

    test('skips emission when devex token is not configured', async () => {
        const fetchMock = jest.fn(fetchOk)
        const github = createGithubMock({ core: snapshot({ remaining: 1, limit: 15000 }) })
        const core = createCore()

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        expect(fetchMock).not.toHaveBeenCalled()
        expect(core.warning).toHaveBeenCalledWith(expect.stringContaining('POSTHOG_DEVEX_PROJECT_API_TOKEN'))
    })
})
