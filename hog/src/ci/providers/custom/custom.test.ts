import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'
import { parseHost } from '@/posthog/host'
import { fakeRuntime } from '@/testing'

import { GITLAB } from '../gitlab/gitlab'
import { detectWorkloadProvider } from '../registry'
import { CUSTOM_OIDC } from './custom'

const OIDC_TOKEN = 'eyJoZWFkZXIi.eyJwYXlsb2FkIi.c2lnbmF0dXJl'

describe('custom OIDC provider', () => {
    test.each([
        ['a job with only HOG_ID_TOKEN', { HOG_ID_TOKEN: OIDC_TOKEN }, 'custom'],
        [
            'a gitlab.com job, which sets the same variable',
            { HOG_ID_TOKEN: OIDC_TOKEN, GITLAB_CI: 'true', CI_SERVER_URL: 'https://gitlab.com' },
            'gitlab',
        ],
        ['a job without a token', {}, undefined],
    ])('picks the provider for %s, with the custom provider after GitLab', (_name, env, expected) => {
        expect(detectWorkloadProvider(env, [GITLAB, CUSTOM_OIDC])?.key).toBe(expected)
    })

    test.each([
        ['the token in HOG_ID_TOKEN', { HOG_ID_TOKEN: OIDC_TOKEN }, OIDC_TOKEN],
        ['a value that is no JWT', { HOG_ID_TOKEN: 'not-a-token' }, 'invalid_oidc_token'],
    ])('reads %s', async (_name, env, expected) => {
        const outcome = await CUSTOM_OIDC.fetchToken(fakeRuntime({ env }), parseHost('https://us.posthog.com')).catch(
            (error: unknown) => error
        )

        expect(outcome instanceof HogError ? outcome.code : String(outcome)).toBe(expected)
    })
})
