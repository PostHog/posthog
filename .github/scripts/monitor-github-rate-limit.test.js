// Run with: node --test .github/scripts/monitor-github-rate-limit.test.js

const { describe, it, beforeEach } = require('node:test')
const assert = require('node:assert/strict')

const monitor = require('./monitor-github-rate-limit')

const T_BASE = new Date('2026-04-27T18:00:00Z')
const T_BASE_SECONDS = Math.floor(T_BASE.getTime() / 1000)

const snapshot = ({ remaining, limit, resetSecondsFromBase = 1800 }) => ({
    remaining,
    limit,
    used: limit - remaining,
    reset: T_BASE_SECONDS + resetSecondsFromBase,
})

// Minimal call-recording mock (no jest in the node:test runner).
function recordingFn(impl) {
    const fn = (...args) => {
        fn.calls.push(args)
        return impl ? impl(...args) : undefined
    }
    fn.calls = []
    return fn
}

// Subset match: every key in `expected` must deep-equal the same key in
// `actual` (node:test has no jest-style toMatchObject).
function assertMatch(actual, expected, path = '') {
    for (const [key, want] of Object.entries(expected)) {
        const got = actual == null ? undefined : actual[key]
        const at = path ? `${path}.${key}` : key
        if (want && typeof want === 'object') {
            assertMatch(got, want, at)
        } else {
            assert.equal(got, want, `mismatch at ${at}`)
        }
    }
}

const calledWith = (fn, ...expected) =>
    fn.calls.some((args) => args.length === expected.length && args.every((a, i) => a === expected[i]))
const calledWithStringContaining = (fn, sub) =>
    fn.calls.some((args) => args.some((a) => typeof a === 'string' && a.includes(sub)))

const createGithubMock = (resources) => ({
    rest: { rateLimit: { get: () => Promise.resolve({ data: { resources } }) } },
})

const createCore = () => ({ info: recordingFn(), warning: recordingFn(), setOutput: recordingFn() })

const fetchOk = () => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('ok') })

const context = { repo: { owner: 'PostHog', repo: 'posthog' } }

describe('monitor-github-rate-limit', () => {
    beforeEach(() => {
        delete process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN
    })

    it('emits one event per resource with the expected payload shape', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        const captured = []
        const fetchMock = recordingFn((_url, opts) => {
            captured.push(JSON.parse(opts.body))
            return fetchOk()
        })
        const github = createGithubMock({
            core: snapshot({ remaining: 3000, limit: 15000, resetSecondsFromBase: 600 }),
            graphql: snapshot({ remaining: 5000, limit: 5000 }),
        })
        const core = createCore()

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        assert.equal(captured.length, 2)
        assertMatch(captured[0], {
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
        assert.ok(Math.abs(captured[0].properties.utilization - 12000 / 15000) < 1e-9)
        assert.ok(calledWith(core.setOutput, 'emitted', '2'))
    })

    it('tags emissions with the offload bucket source when overridden', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        const captured = []
        const fetchMock = recordingFn((_url, opts) => {
            captured.push(JSON.parse(opts.body))
            return fetchOk()
        })
        const github = createGithubMock({ core: snapshot({ remaining: 14500, limit: 15000 }) })
        const core = createCore()

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock, source: 'posthog-devex-general' })

        assertMatch(captured[0].properties, {
            resource: 'core',
            remaining: 14500,
            limit: 15000,
            source: 'posthog-devex-general',
        })
    })

    it('counts capture failures without aborting later emissions', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        let calls = 0
        const fetchMock = recordingFn(() =>
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

        assert.ok(calledWith(core.setOutput, 'emitted', '1'))
        assert.ok(calledWith(core.setOutput, 'failures', '1'))
        assert.ok(calledWithStringContaining(core.warning, 'capture 500'))
    })

    it('captures the triggering event context on each sample', async () => {
        process.env.POSTHOG_DEVEX_PROJECT_API_TOKEN = 'devex-key'
        const captured = []
        const fetchMock = recordingFn((_url, opts) => {
            captured.push(JSON.parse(opts.body))
            return fetchOk()
        })
        const github = createGithubMock({ core: snapshot({ remaining: 3000, limit: 15000 }) })
        const core = createCore()
        const prContext = {
            repo: { owner: 'PostHog', repo: 'posthog' },
            eventName: 'pull_request',
            payload: {
                action: 'synchronize',
                pull_request: {
                    number: 12345,
                    head: { ref: 'feature/foo' },
                    user: { login: 'octocat' },
                    changed_files: 7,
                    additions: 120,
                    deletions: 4,
                },
            },
        }

        await monitor({ github, context: prContext, core }, { now: () => T_BASE, fetch: fetchMock })

        assertMatch(captured[0].properties, {
            trigger_event: 'pull_request',
            trigger_action: 'synchronize',
            head_ref: 'feature/foo',
            pr_number: 12345,
            pr_author: 'octocat',
            pr_changed_files: 7,
            pr_additions: 120,
            pr_deletions: 4,
        })
    })

    for (const [eventName, payload, expectedRef] of [
        ['push', { ref: 'refs/heads/master' }, 'master'],
        ['schedule', {}, null],
        ['workflow_dispatch', {}, null],
    ]) {
        it(`buildTrigger nulls PR fields and resolves head_ref for non-PR event ${eventName}`, () => {
            assertMatch(monitor.buildTrigger({ eventName, payload }), {
                trigger_event: eventName,
                trigger_action: null,
                head_ref: expectedRef,
                pr_number: null,
                pr_author: null,
                pr_changed_files: null,
                pr_additions: null,
                pr_deletions: null,
            })
        })
    }

    it('skips emission when devex token is not configured', async () => {
        const fetchMock = recordingFn(fetchOk)
        const github = createGithubMock({ core: snapshot({ remaining: 1, limit: 15000 }) })
        const core = createCore()

        await monitor({ github, context, core }, { now: () => T_BASE, fetch: fetchMock })

        assert.equal(fetchMock.calls.length, 0)
        assert.ok(calledWithStringContaining(core.warning, 'POSTHOG_DEVEX_PROJECT_API_TOKEN'))
    })
})
