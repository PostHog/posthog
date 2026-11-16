import { describe, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { z } from 'zod'

import { HogError } from '@/core/errors'
import type { Secrets } from '@/core/runtime'
import { fakeRuntime, readJson, type FakeRuntime } from '@/testing'

import { PostHogApi } from './api'
import { resolveCredentials, type Credentials } from './credentials'
import { parseHost } from './host'
import { KeySession } from './key-session'
import { HOG_CLIENT_ID } from './oauth'

const SettingsLogins = z.object({ logins: z.record(z.string(), z.record(z.string(), z.unknown())) })

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

function sessionFor(runtime: FakeRuntime, credentials: Credentials): KeySession {
    return new KeySession(runtime, credentials.key, credentials.source === 'store' ? credentials.storage : null)
}

const OK = { name: 'Hedgebox' }
const REJECTED = { status: 401 }

function tokenRequests(runtime: FakeRuntime): FakeRuntime['requests'] {
    return runtime.requests.filter((request) => request.url === `${EU}/oauth/token/`)
}

describe('OAuth credentials', () => {
    test.each([
        ['renews a token PostHog rejects and sends the request once more', 3_600_000, 0, 'pha_new', 2, OK],
        ['renews a token about to expire mid-command before it sends', 11 * 60_000, 2 * 60_000, 'pha_new', 1, OK],
        ['surfaces a second 401 instead of retrying again', 3_600_000, 0, 'pha_also_rejected', 2, REJECTED],
    ])('a request %s', async (_name, expiresInMs, commandRunsMs, renewedToken, apiCalls, expected) => {
        const runtime = fakeRuntime({
            ...stored('pha_old', expiresInMs),
            respond: (url, _body, authorization) => {
                if (url === `${EU}/oauth/token/`) {
                    return { status: 200, body: { access_token: renewedToken, expires_in: 3600 } }
                }
                return authorization === 'Bearer pha_new'
                    ? { status: 200, body: { name: 'Hedgebox' } }
                    : { status: 401, body: { detail: 'Invalid token' } }
            },
        })
        const api = new PostHogApi(sessionFor(runtime, await resolveCredentials(runtime, {})), runtime.fetch)
        await runtime.sleep(commandRunsMs)

        const outcome = await api.get('', z.looseObject({ name: z.string() })).catch((error: unknown) => error)

        expect(outcome).toMatchObject(expected)
        expect(tokenRequests(runtime)).toHaveLength(1)
        expect(runtime.requests.filter((request) => request.url.includes('/api/'))).toHaveLength(apiCalls)
        expect(readJson(runtime.keychain[EU] ?? '{}')).toMatchObject({ accessToken: renewedToken })
    })

    test('a 401 that a renewed token gets too stops renewing for the rest of the command', async () => {
        const runtime = fakeRuntime({
            ...stored('pha_old', 3_600_000),
            respond: (url) =>
                url === `${EU}/oauth/token/`
                    ? { status: 200, body: { access_token: 'pha_new', expires_in: 3600 } }
                    : { status: 401, body: { detail: 'This account is not active' } },
        })
        const api = new PostHogApi(sessionFor(runtime, await resolveCredentials(runtime, {})), runtime.fetch)

        const outcomes = [
            await api.get('', z.unknown()).catch((error: unknown) => error),
            await api.get('', z.unknown()).catch((error: unknown) => error),
        ]

        expect(outcomes).toMatchObject([REJECTED, REJECTED])
        expect(tokenRequests(runtime)).toHaveLength(1)
        expect(runtime.requests.filter((request) => request.url.includes('/api/'))).toHaveLength(3)
    })

    test('a login that replaced this one mid-command stops it instead of sending to its project', async () => {
        const runtime = fakeRuntime({
            ...stored('pha_old', 3_600_000),
            respond: () => ({ status: 401, body: { detail: 'Invalid token' } }),
        })
        const api = new PostHogApi(sessionFor(runtime, await resolveCredentials(runtime, {})), runtime.fetch)
        const replaced = readJson(settings(3_600_000), SettingsLogins)
        replaced.logins[EU] = { ...replaced.logins[EU], projectId: '99', loginId: 'login-2' }
        runtime.files[SETTINGS_FILE] = JSON.stringify(replaced)
        runtime.keychain[EU] = secret('pha_other')

        const outcome = await api.get('', z.unknown()).catch((error: unknown) => error)

        expect(outcome).toMatchObject({ code: 'login_changed' })
        expect(tokenRequests(runtime)).toEqual([])
    })

    test('a stored personal API key that PostHog rejects is sent only once', async () => {
        const record = { store: 'keychain', type: 'personal_api_key', projectId: '42', host: EU }
        const runtime = fakeRuntime({
            files: { [SETTINGS_FILE]: JSON.stringify({ logins: { [EU]: record }, host: EU }) },
            keychain: { [EU]: JSON.stringify({ apiKey: 'phx_deleted' }) },
            respond: () => ({ status: 401, body: { detail: 'Invalid personal API key' } }),
        })
        const api = new PostHogApi(sessionFor(runtime, await resolveCredentials(runtime, {})), runtime.fetch)

        const outcome = await api.get('', z.unknown()).catch((error: unknown) => error)

        expect(outcome).toMatchObject(REJECTED)
        expect(runtime.requests).toHaveLength(1)
    })

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
        expect(readJson(runtime.keychain[EU] ?? '{}')).toEqual({ accessToken: 'pha_new', refreshToken: 'phr_old' })
        expect(readJson(runtime.files[SETTINGS_FILE] ?? '{}', SettingsLogins).logins[EU]).toMatchObject({
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
        expect(readJson(runtime.keychain[EU] ?? '{}')).toEqual({ accessToken: 'pha_new', refreshToken: 'phr_new' })
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

        const error = await resolveCredentials(runtime, { configHost: parseHost('https://us.posthog.com') }).catch(
            (caught: unknown) => caught
        )

        expect((error as HogError).code).toBe('host_mismatch')
        expect(tokenRequests(runtime)).toEqual([])
    })
})
