import { describe, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'

import { HogError } from '@/core/errors'
import type { Secrets } from '@/core/runtime'
import { fakeRuntime, type FakeRuntime } from '@/testing'

import { resolveCredentials } from './credentials'
import { HOG_CLIENT_ID } from './oauth'

const EU = 'https://eu.posthog.com'
const START = Date.UTC(2026, 0, 1)
const SETTINGS_FILE = '/home/test/.config/hog/settings.json'
const LOCK = /^\/home\/test\/\.config\/hog\/refresh-[0-9a-f]+\.lock$/

// settings.json keeps what isn't secret about the login, and the keychain keeps the tokens.
function settings(expiresInMs: number): string {
    const record = {
        store: 'keychain',
        type: 'oauth',
        projectId: '42',
        host: EU,
        expiresAt: START + expiresInMs,
        scopes: ['openid', 'insight:read'],
        loginId: 'login-1',
    }
    return JSON.stringify({ logins: { [EU]: record }, host: EU })
}

function secret(accessToken: string): string {
    return JSON.stringify({ accessToken, refreshToken: 'phr_old' })
}

function stored(
    accessToken: string,
    expiresInMs: number
): { files: Record<string, string>; keychain: Record<string, string> } {
    return { files: { [SETTINGS_FILE]: settings(expiresInMs) }, keychain: { [EU]: secret(accessToken) } }
}

function tokenRequests(runtime: FakeRuntime): FakeRuntime['requests'] {
    return runtime.requests.filter((request) => request.url === `${EU}/oauth/token/`)
}

describe('OAuth credentials', () => {
    test('renew a token about to expire, keeping the refresh token PostHog did not rotate', async () => {
        const runtime = fakeRuntime({
            ...stored('pha_old', 30_000),
            respond: () => ({ status: 200, body: { access_token: 'pha_new', expires_in: 3600, scope: 'openid' } }),
        })

        const credentials = await resolveCredentials(runtime, {})

        expect(credentials.key).toMatchObject({ token: 'pha_new', projectId: '42' })
        expect(credentials.key.status()).toMatchObject({ kind: 'oauth', scopes: ['openid'] })
        expect(tokenRequests(runtime).map((request) => request.body)).toEqual([
            { grant_type: 'refresh_token', refresh_token: 'phr_old', client_id: HOG_CLIENT_ID },
        ])
        expect(JSON.parse(runtime.keychain[EU] ?? '{}')).toEqual({ accessToken: 'pha_new', refreshToken: 'phr_old' })
        expect(JSON.parse(runtime.files[SETTINGS_FILE] ?? '{}').logins[EU]).toMatchObject({
            expiresAt: START + 3_600_000,
            scopes: ['openid'],
            loginId: 'login-1',
        })
        expect(Object.keys(runtime.files).filter((path) => LOCK.test(path))).toEqual([])
    })

    test('retry a renewal whose answer got lost, and keep the rotated refresh token', async () => {
        let calls = 0
        const runtime = fakeRuntime({
            ...stored('pha_old', 30_000),
            respond: () => {
                calls += 1
                if (calls === 1) {
                    throw new Error('connection reset')
                }
                return { status: 200, body: { access_token: 'pha_new', refresh_token: 'phr_new', expires_in: 3600 } }
            },
        })

        const credentials = await resolveCredentials(runtime, {})

        expect(credentials.key).toMatchObject({ token: 'pha_new' })
        expect(tokenRequests(runtime)).toHaveLength(2)
        expect(JSON.parse(runtime.keychain[EU] ?? '{}')).toEqual({ accessToken: 'pha_new', refreshToken: 'phr_new' })
    })

    test('use a token with time left as it is', async () => {
        const runtime = fakeRuntime({
            ...stored('pha_old', 3_600_000),
        })

        expect((await resolveCredentials(runtime, {})).key).toMatchObject({ token: 'pha_old' })
        expect(runtime.requests).toEqual([])
    })

    test.each([
        ['a lock its owner left behind', JSON.stringify({ id: 'theirs', createdAt: START - 179_000 }), 1_000],
        ['a lock nobody can read', '', 180_000],
    ])('take over %s, and use the token its owner stored', async (_name, lockContents, minimumWaitMs) => {
        // The first read finds the expiring token. By the time hog holds the lock, settings.json and
        // the keychain have the login the other process renewed before it died.
        let reads = 0
        const secrets = (): Secrets => ({
            get: async () => secret(reads++ === 0 ? 'pha_old' : 'pha_theirs'),
            set: async () => {},
            delete: async () => true,
        })
        const runtime = fakeRuntime({ files: { [SETTINGS_FILE]: settings(30_000) }, secrets })
        const readFile = runtime.readFile
        let settingsReads = 0
        runtime.readFile = async (path) =>
            path === SETTINGS_FILE && settingsReads++ > 0 ? settings(3_600_000) : readFile(path)
        const lock = `/home/test/.config/hog/refresh-${createHash('sha256').update(EU).digest('hex').slice(0, 16)}.lock`
        runtime.files[lock] = lockContents

        const credentials = await resolveCredentials(runtime, {})

        expect(credentials.key).toMatchObject({ token: 'pha_theirs' })
        expect(tokenRequests(runtime)).toEqual([])
        expect(runtime.files[lock]).toBeUndefined()
        expect(runtime.now() - START).toBeGreaterThan(minimumWaitMs)
    })

    test('a revoked refresh token says to log in again', async () => {
        const runtime = fakeRuntime({
            ...stored('pha_old', 30_000),
            respond: () => ({ status: 400, body: { error: 'invalid_grant' } }),
        })

        const error = await resolveCredentials(runtime, {}).catch((caught: unknown) => caught)

        expect(error).toBeInstanceOf(HogError)
        expect((error as HogError).code).toBe('session_expired')
    })

    test('a login for another host than posthog.json names fails before hog renews it', async () => {
        const runtime = fakeRuntime({
            ...stored('pha_old', 30_000),
            respond: () => ({ status: 200, body: { access_token: 'pha_new', expires_in: 3600 } }),
        })

        const error = await resolveCredentials(runtime, { configHost: 'https://us.posthog.com' }).catch(
            (caught: unknown) => caught
        )

        expect((error as HogError).code).toBe('host_mismatch')
        expect(tokenRequests(runtime)).toEqual([])
    })
})
