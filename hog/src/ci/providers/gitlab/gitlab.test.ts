import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'
import { parseHost } from '@/posthog/host'
import { fakeRuntime } from '@/testing'

import { GITLAB } from './gitlab'

const OIDC_TOKEN = 'eyJoZWFkZXIi.eyJwYXlsb2FkIi.c2lnbmF0dXJl'
const HOST = parseHost('https://us.posthog.com')

describe('GitLab', () => {
    test.each([
        ['the id_tokens variable', { HOG_ID_TOKEN: OIDC_TOKEN }, OIDC_TOKEN],
        ['a job without the id_tokens entry', {}, undefined],
        ['a variable that holds something else', { HOG_ID_TOKEN: 'glpat-not-a-jwt' }, 'invalid_oidc_token'],
    ])('reads the token from %s', async (_name, env, expected) => {
        const outcome = await GITLAB.fetchToken(fakeRuntime({ env }), HOST).catch((error: unknown) => error)

        expect(outcome instanceof HogError ? outcome.code : outcome === undefined ? undefined : String(outcome)).toBe(
            expected
        )
    })

    test.each([
        ['a gitlab.com job', { GITLAB_CI: 'true', CI_SERVER_URL: 'https://gitlab.com' }, true],
        // A self-managed instance is its own issuer, which PostHog doesn't trust.
        ['a self-managed GitLab job', { GITLAB_CI: 'true', CI_SERVER_URL: 'https://gitlab.example.com' }, false],
    ])('detects %s', (_name, env, expected) => {
        expect(GITLAB.detect(env)).toBe(expected)
    })

    test.each([
        ['git@gitlab.com:acme/tools/web.git', 'acme/tools/web'],
        ['https://gitlab.com/acme/web', 'acme/web'],
        ['git@github.com:acme/web.git', undefined],
        ['https://evil.example.com/gitlab.com/acme/web', undefined],
        ['https://gitlab.com/acme/web.git?private_token=secret', undefined],
    ])('reads the project path from the remote %s', (remote, expected) => {
        expect(GITLAB.nameFromRemote(remote)).toBe(expected)
    })
})
