import { describe, expect, test } from 'bun:test'

import type { WorkloadProvider } from '@/ci/providers'
import { HogError } from '@/core/errors'
import { FAKE_WORKLOAD_PROVIDER, fakeRuntime, type FakeRuntimeOptions } from '@/testing'

import { resolveCredentials } from './credentials'
import { parseHost } from './host'
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
                projectId: '9',
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

    test.each([
        ['a posthog.json Cloud region', {}, 'https://eu.posthog.com/', 'https://eu.posthog.com'],
        [
            'HOG_HOST over posthog.json',
            { host: 'https://ph.example.com' },
            'https://eu.posthog.com',
            'https://ph.example.com',
        ],
        [
            'US Cloud over a posthog.json host that is no Cloud region',
            {},
            'https://attacker.example',
            'https://us.posthog.com',
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
    ])('a refused exchange where %s says what to do next', async (_name, body, code, hint) => {
        const runtime = runtimeWith({ env: IN_CI, respond: () => ({ status: 400, body }) })
        const error = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] }).catch((e) => e)

        expect(error).toBeInstanceOf(HogError)
        expect((error as HogError).code).toBe(code)
        expect((error as HogError).hint).toContain(hint)
    })

    test('waits once when the repository used up its exchanges for a moment', async () => {
        let calls = 0
        const runtime = runtimeWith({
            env: IN_CI,
            respond: () =>
                calls++ === 0
                    ? { status: 429, body: { error_code: 'workload_rate_limited', retry_after: 3 } }
                    : exchanged(WORKLOAD_TOKEN),
        })
        const start = runtime.now()

        const credentials = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] })

        expect(credentials.source).toBe('workload')
        expect(runtime.now() - start).toBe(3000)
    })

    test('a job with no credentials at all names the fix in the job', async () => {
        const runtime = runtimeWith({ env: { ...IN_CI, FAKE_CI_TOKEN: '' } })
        const error = await resolveCredentials(runtime, { workloadProviders: [FAKE_PROVIDER] }).catch((e) => e)

        expect((error as HogError).code).toBe('not_authenticated')
        expect((error as HogError).hint).toContain('Turn on OIDC tokens in Fake CI.')
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
