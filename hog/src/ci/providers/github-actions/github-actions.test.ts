import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'
import { parseHost } from '@/posthog/host'
import { fakeRuntime } from '@/testing'

import { GITHUB_ACTIONS } from './github-actions'

const OIDC_TOKEN = 'eyJoZWFkZXIi.eyJwYXlsb2FkIi.c2lnbmF0dXJl'
const REQUEST_URL = 'https://pipelines.actions.example/idtoken?api-version=2.0'
const JOB = {
    GITHUB_ACTIONS: 'true',
    ACTIONS_ID_TOKEN_REQUEST_URL: REQUEST_URL,
    ACTIONS_ID_TOKEN_REQUEST_TOKEN: 'request-secret',
}

describe('GitHub Actions', () => {
    test('asks for a token whose audience is the PostHog host, with the job request token', async () => {
        const seen: { url: string; authorization: string | null }[] = []
        const runtime = fakeRuntime({
            env: JOB,
            respond: (url, _body, authorization) => {
                seen.push({ url, authorization })
                return { status: 200, body: { value: OIDC_TOKEN } }
            },
        })

        const token = await GITHUB_ACTIONS.fetchToken(runtime, parseHost('https://eu.posthog.com'))

        expect(String(token)).toBe(OIDC_TOKEN)
        expect(seen).toEqual([
            {
                url: `${REQUEST_URL}&audience=https%3A%2F%2Feu.posthog.com`,
                authorization: 'Bearer request-secret',
            },
        ])
    })

    test.each([
        ['a job without id-token: write', { GITHUB_ACTIONS: 'true' }, undefined],
        ['GitHub refusing the request', JOB, 'oidc_token_unavailable'],
        [
            'a request token a header cannot carry',
            { ...JOB, ACTIONS_ID_TOKEN_REQUEST_TOKEN: 'request-\nsecret' },
            'network_error',
        ],
    ])('%s gets no token', async (_name, env, code) => {
        const runtime = fakeRuntime({ env, respond: () => ({ status: 403, body: {} }) })

        const outcome = await GITHUB_ACTIONS.fetchToken(runtime, parseHost('https://us.posthog.com')).catch(
            (error: unknown) => error
        )

        expect(outcome instanceof HogError ? outcome.code : outcome).toBe(code)
        expect(outcome instanceof HogError ? outcome.message : '').not.toContain('secret')
    })

    test.each([
        ['a GitHub Actions job', { GITHUB_ACTIONS: 'true' }, true],
        ['a local shell', {}, false],
    ])('detects %s', (_name, env, expected) => {
        expect(GITHUB_ACTIONS.detect(env)).toBe(expected)
    })

    test.each([
        ['git@github.com:PostHog/posthog.git', 'PostHog/posthog'],
        ['https://github.com/PostHog/posthog', 'PostHog/posthog'],
        ['ssh://git@github.com/PostHog/posthog.git', 'PostHog/posthog'],
        ['git@gitlab.com:PostHog/posthog.git', undefined],
        ['https://notgithub.com/PostHog/posthog.git', undefined],
        ['https://evil.example.com/github.com/PostHog/posthog', undefined],
        ['https://github.com/PostHog/posthog\x1b]0;x\x07', undefined],
    ])('reads the repository from the remote %s', (remote, expected) => {
        expect(GITHUB_ACTIONS.nameFromRemote(remote)).toBe(expected)
    })
})
