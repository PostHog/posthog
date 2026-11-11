import { describe, expect, test } from 'bun:test'
import { z } from 'zod'

import type { WorkloadProvider } from '@/ci/providers/registry'
import { HogError } from '@/core/errors'
import { Telemetry } from '@/core/telemetry'
import { FAKE_WORKLOAD_PROVIDER, fakeRuntime, type FakeRuntimeOptions } from '@/testing'

import { PostHogApi } from './api'
import { resolveCredentials } from './credentials'
import { parseHost } from './host'
import { parseProjectId } from './ids'
import { KeySession } from './key-session'

const OIDC_TOKEN = 'eyJoZWFkZXIi.eyJwYXlsb2FkIi.c2lnbmF0dXJl'
const WORKLOAD_TOKEN = 'eyJ3b3JrbG9hZCI.eyJ0b2tlbiI.c2lnbmVk'
const RENEWED_TOKEN = 'eyJyZW5ld2VkIg.eyJ0b2tlbiI.c2lnbmVk'
const SETTINGS_FILE = '/home/test/.config/hog/settings.json'
const STORED_LOGIN = {
    [SETTINGS_FILE]: JSON.stringify({
        host: 'https://us.posthog.com',
        logins: {
            'https://us.posthog.com': {
                store: 'file',
                type: 'personal_api_key',
                projectId: '42',
                host: 'https://us.posthog.com',
            },
        },
    }),
    '/home/test/.config/hog/credentials.json': JSON.stringify({
        'https://us.posthog.com': { apiKey: 'phx_stored' },
    }),
}

const audiences: string[] = []

const FAKE_PROVIDER: WorkloadProvider = {
    ...FAKE_WORKLOAD_PROVIDER,
    fetchToken: async (runtime, audience) => {
        audiences.push(audience)
        return FAKE_WORKLOAD_PROVIDER.fetchToken(runtime, audience)
    },
}

const IN_CI = { FAKE_CI: 'true', FAKE_CI_TOKEN: OIDC_TOKEN, HOG_PROJECT_ID: '42' }

function exchanged(token: string, expiresIn = 600): { status: number; body: unknown } {
    return { status: 200, body: { access_token: token, expires_in: expiresIn, scope: 'insight:read' } }
}

function runtimeWith(options: FakeRuntimeOptions): ReturnType<typeof fakeRuntime> {
    audiences.length = 0
    return fakeRuntime(options)
}

describe('workload credentials', () => {
    test.each([
        ['a personal API key in the environment wins', { ...IN_CI, HOG_PERSONAL_API_KEY: 'phx_env' }, 'env'],
        ['the OIDC token comes before a stored login', IN_CI, 'workload'],
        ['a job without an OIDC token falls back to the stored login', { ...IN_CI, FAKE_CI_TOKEN: '' }, 'store'],
        ['a job without HOG_PROJECT_ID falls back to the stored login', { ...IN_CI, HOG_PROJECT_ID: '' }, 'store'],
    ] as const)('%s', async (_name, env, source) => {
        const runtime = runtimeWith({ env, files: STORED_LOGIN, respond: () => exchanged(WORKLOAD_TOKEN) })
        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })
        expect(credentials.source).toBe(source)
    })

    test('a posthog.json host outside PostHog Cloud stops the job instead of getting a token', async () => {
        const runtime = runtimeWith({ env: IN_CI, respond: () => exchanged(WORKLOAD_TOKEN) })

        const error = await resolveCredentials(runtime, {
            workloadProviders: [FAKE_PROVIDER],
            configHost: parseHost('https://attacker.example'),
        }).catch((e: unknown) => e)

        expect((error as HogError).code).toBe('workload_host_not_allowed')
        expect(runtime.requests).toEqual([])
    })

    test('a job takes its project from posthog.json', async () => {
        const runtime = runtimeWith({ env: { ...IN_CI, HOG_PROJECT_ID: '' }, respond: () => exchanged(WORKLOAD_TOKEN) })

        const credentials = await resolveCredentials(runtime, {
            workloadProviders: [FAKE_PROVIDER],
            configProjectId: parseProjectId('42'),
        })

        expect(credentials.source).toBe('workload')
        expect(String(credentials.key.projectId)).toBe('42')
    })

    test.each([
        ['a posthog.json Cloud region', {}, 'https://eu.posthog.com/', 'https://eu.posthog.com'],
        [
            'HOG_HOST over posthog.json',
            { host: 'https://ph.example.com' },
            'https://eu.posthog.com',
            'https://ph.example.com',
        ],
    ])('asks for a token for the host it sends it to: %s', async (_name, flags, configHost, expected) => {
        const runtime = runtimeWith({ env: IN_CI, respond: () => exchanged(WORKLOAD_TOKEN) })
        const credentials = await resolveCredentials(runtime, {
            workloadProviders: [FAKE_PROVIDER],
            host: 'host' in flags ? parseHost(flags.host) : undefined,
            configHost: parseHost(configHost),
        })

        expect(audiences).toEqual([expected])
        expect(runtime.requests).toEqual([
            {
                method: 'POST',
                url: `${expected}/oauth/token/`,
                body: {
                    grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange',
                    subject_token: OIDC_TOKEN,
                    subject_token_type: 'urn:ietf:params:oauth:token-type:id_token',
                    resource: `${expected}/api/projects/42`,
                },
            },
        ])
        expect(String(credentials.key.token)).toBe(WORKLOAD_TOKEN)
    })

    test.each([
        [
            'no policy matches',
            {
                error: 'invalid_grant',
                error_description: 'No workload trust policy in project 42 matches this workload.',
                error_code: 'workload_no_matching_policy',
                claims: { provider: 'fake_ci', subject: '1', subject_name: 'acme/web', conditions: {} },
            },
            'workload_no_matching_policy',
            'hog ci setup',
        ],
        [
            'the policy request waits for an admin',
            {
                error: 'invalid_grant',
                error_description: 'A workload trust policy for this job is waiting for an admin to approve it.',
                error_code: 'workload_policy_request_pending',
                approval_url: 'https://us.posthog.com/approve/1',
            },
            'workload_policy_request_pending',
            'https://us.posthog.com/approve/1',
        ],
        [
            'the token is for another PostHog address',
            {
                error: 'invalid_grant',
                error_description: "The OIDC token's audience must be https://us.posthog.com.",
                error_code: 'workload_audience_mismatch',
            },
            'workload_audience_mismatch',
            'HOG_HOST',
        ],
    ])('a refused exchange where %s says what to do next', async (_name, body, code, hint) => {
        const runtime = runtimeWith({ env: IN_CI, respond: () => ({ status: 400, body }) })
        const error = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] }).catch((e) => e)

        expect(error).toBeInstanceOf(HogError)
        expect((error as HogError).code).toBe(code)
        expect((error as HogError).hint).toContain(hint)
    })

    test('waits a little past the hint while the repository has used up its exchanges', async () => {
        let calls = 0
        const runtime = runtimeWith({
            env: IN_CI,
            respond: () =>
                calls++ < 2
                    ? { status: 429, body: { error_code: 'workload_rate_limited', retry_after: 3 } }
                    : exchanged(WORKLOAD_TOKEN),
        })
        const start = runtime.now()

        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })

        expect(credentials.source).toBe('workload')
        expect(runtime.now() - start).toBeGreaterThanOrEqual(6000)
        expect(runtime.now() - start).toBeLessThan(12_000)
    })

    test('usage data counts a job under its workload, never a person or the repository ID', async () => {
        const payload = { org_id: 'org-uuid', workload: { provider: 'fake_ci', subject: '1234' } }
        const token = `eyJhbGciOiJSUzI1NiJ9.${Buffer.from(JSON.stringify(payload)).toString('base64url')}.c2ln`
        const runtime = fakeRuntime({ env: IN_CI, telemetryToken: 'phc_test', respond: () => exchanged(token) })
        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })
        const mode = {
            agent: undefined,
            agentReason: '',
            format: 'json',
            color: false,
            columns: undefined,
            ci: true,
        } as const
        const telemetry = new Telemetry(runtime, mode, true)
        telemetry.credentials = async () => credentials

        telemetry.capture('hog command run')
        await telemetry.flush()

        const { batch } = runtime.requests.at(-1)!.body as { batch: { distinct_id: string; properties: object }[] }
        expect(batch[0]!.distinct_id).toMatch(/^workload_[0-9a-f]{32}$/)
        expect(JSON.stringify(batch)).not.toContain('1234')
        expect(batch[0]!.properties).toMatchObject({
            credential_type: 'workload',
            workload_provider: 'fake_ci',
            $process_person_profile: false,
            $groups: { organization: 'org-uuid' },
        })
    })

    test('a job with no credentials at all names the fix in the job', async () => {
        const runtime = runtimeWith({ env: { ...IN_CI, FAKE_CI_TOKEN: '' } })
        const error = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] }).catch((e) => e)

        expect((error as HogError).code).toBe('not_authenticated')
        expect((error as HogError).hint).toContain('Turn on OIDC tokens in Fake CI.')
    })

    test("a job's token never steps up, and a missing scope points to the trusted workload policy", async () => {
        const runtime = runtimeWith({
            env: IN_CI,
            respond: (url) =>
                url.endsWith('/oauth/token/')
                    ? exchanged(WORKLOAD_TOKEN)
                    : {
                          status: 403,
                          body: { detail: 'missing scope' },
                          headers: { 'WWW-Authenticate': 'Bearer error="insufficient_scope", scope="query:read"' },
                      },
        })
        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })
        const stepUps: string[][] = []
        const api = new PostHogApi(
            new KeySession(runtime, credentials.key, credentials.storage),
            runtime.fetch,
            async (scopes) => {
                stepUps.push([...scopes])
                return true
            }
        )

        const error = await api.get('/query', z.unknown()).catch((caught: unknown) => caught)

        expect(stepUps).toEqual([])
        expect(error).toMatchObject({
            code: 'missing_scopes',
            hint: expect.stringContaining('trusted workload policy'),
        })
    })

    test('a provider token fixed for the run is not exchanged again before the PostHog token expires', async () => {
        // Each answer arrives a little later than whole seconds, so it reads like a later expiry.
        const lifetimes = [120, 60, 21]
        let exchangeCount = 0
        const runtime = runtimeWith({
            env: IN_CI,
            respond: () => exchanged(exchangeCount ? RENEWED_TOKEN : WORKLOAD_TOKEN, lifetimes[exchangeCount++]),
        })
        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })
        const session = new KeySession(runtime, credentials.key, credentials.storage)

        await runtime.sleep(61_000)
        await session.token()
        await runtime.sleep(39_000)
        await session.token()

        expect(exchangeCount).toBe(2)
    })

    test('a failed exchange fails every concurrent request instead of each one trying again', async () => {
        let exchangeCount = 0
        const runtime = runtimeWith({
            env: IN_CI,
            respond: (url) =>
                !url.endsWith('/oauth/token/')
                    ? { status: 200, body: {} }
                    : ++exchangeCount === 1
                      ? exchanged(WORKLOAD_TOKEN)
                      : { status: 503, body: { error: 'temporarily_unavailable' } },
        })
        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })
        const session = new KeySession(runtime, credentials.key, credentials.storage)
        await runtime.sleep(560_000)

        const outcomes = await Promise.allSettled([session.token(), session.token(), session.token()])

        expect(outcomes.map((outcome) => outcome.status)).toEqual(['rejected', 'rejected', 'rejected'])
        expect(exchangeCount).toBe(2)
    })

    test.each([
        ['exchanges once more when the token is about to expire', 600, 560, 200, 2],
        ['exchanges once more when PostHog rejects the token', 600, 0, 401, 2],
        ['keeps a token with time left', 600, 0, 200, 1],
        ['keeps a short-lived token until half its life is over', 30, 0, 200, 1],
    ])(
        '%s, sharing one exchange between concurrent requests',
        async (_name, expiresIn, elapsedSeconds, firstStatus, exchanges) => {
            let exchangeCount = 0
            let rejected = false
            const runtime = runtimeWith({
                env: IN_CI,
                respond: (url, _body, authorization) => {
                    if (url.endsWith('/oauth/token/')) {
                        exchangeCount++
                        return exchangeCount === 1 ? exchanged(WORKLOAD_TOKEN, expiresIn) : exchanged(RENEWED_TOKEN)
                    }
                    if (firstStatus === 401 && authorization === `Bearer ${WORKLOAD_TOKEN}`) {
                        rejected = true
                        return { status: 401, body: {} }
                    }
                    return { status: 200, body: {} }
                },
            })
            const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })
            if (credentials.source !== 'workload') {
                throw new Error('expected a workload key')
            }
            const session = new KeySession(runtime, credentials.key, credentials.storage)
            await runtime.sleep(elapsedSeconds * 1000)
            const send = (): Promise<number> =>
                session.send(
                    async (token) =>
                        (
                            await runtime.fetch('https://us.posthog.com/api/x', {
                                headers: { Authorization: `Bearer ${token}` },
                            })
                        ).status,
                    (status) => status === 401
                )

            const statuses = await Promise.all([send(), send(), send()])

            expect(statuses).toEqual([200, 200, 200])
            expect(exchangeCount).toBe(exchanges)
            expect(rejected).toBe(firstStatus === 401)
        }
    )
})
