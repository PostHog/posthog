import { describe, expect, test } from 'bun:test'

import type { Secrets } from '@/core/runtime'
import { LOGIN_SCOPES } from '@/posthog/device-auth'
import { HOG_CLIENT_ID } from '@/posthog/oauth'
import { readJson, runHog } from '@/testing'

const EU = 'https://eu.posthog.com'
const US = 'https://us.posthog.com'
const EU_ITEM = `${EU}#42`
const LEGACY_CLI_FILE = '/home/test/.posthog/credentials.json'
const SETTINGS_FILE = '/home/test/.config/hog/settings.json'
const HOG_CREDENTIALS_FILE = '/home/test/.config/hog/credentials.json'
const PENDING_FILE = '/home/test/.config/hog/pending-auth-login.json'
const DEVICE_CODE = 'device-secret-123'
// Tokens as long as the ones PostHog issues, so the size check below is realistic.
const ACCESS_TOKEN = `pha_${'a'.repeat(43)}`
const REFRESH_TOKEN = `phr_${'r'.repeat(43)}`
const STEPPED_UP_ACCESS = `pha_${'b'.repeat(43)}`
const STEPPED_UP_REFRESH = `phr_${'s'.repeat(43)}`
const ROWS = { columns: ['total'], results: [[1]], hasMore: false }

interface TestRecord extends Record<string, unknown> {
    host: string
    projectId: string
}

function settingsJson(host: string, ...logins: TestRecord[]): string {
    const byOrigin: Record<string, Record<string, unknown>> = {}
    for (const login of logins) {
        const origin = new URL(login.host).origin
        byOrigin[origin] = { ...byOrigin[origin], [login.projectId]: login }
    }
    return JSON.stringify({ logins: byOrigin, host })
}

function keyRecord(host: string, store = 'keychain', projectId = '42'): TestRecord {
    return { store, type: 'personal_api_key', projectId, host }
}

function withPendingRemovals(
    settings: string,
    ...pendingRemovals: { store: string; host: string; projectId: string | null }[]
): string {
    return JSON.stringify({ ...(readJson(settings) as object), pendingRemovals })
}

// The answers layers of the OAuth server give: RFC 8628 device authorization, then the token
// endpoint's RFC 8628 errors, then a token scoped to the project the person picked.
const DEVICE = {
    device_code: DEVICE_CODE,
    user_code: 'BCDF-GHJK',
    verification_uri: `${EU}/device`,
    verification_uri_complete: `${EU}/device?code=BCDF-GHJK`,
    expires_in: 1800,
    interval: 5,
}
const APPROVED = {
    access_token: ACCESS_TOKEN,
    token_type: 'Bearer',
    expires_in: 604800,
    refresh_token: REFRESH_TOKEN,
    scope: LOGIN_SCOPES.join(' '),
    scoped_teams: [42],
    scoped_organizations: [],
}
const PENDING = JSON.stringify({
    host: EU,
    deviceCode: DEVICE_CODE,
    userCode: 'BCDF-GHJK',
    url: `${EU}/device?code=BCDF-GHJK`,
    expiresAt: Date.UTC(2026, 0, 1) + 1_800_000,
    intervalSeconds: 5,
    scopes: LOGIN_SCOPES,
})

// The device flow: a device code, then `pendingPolls` answers of "keep waiting", then `final`.
function deviceFlow(pendingPolls: number, final = { status: 200, body: APPROVED as unknown }) {
    let polls = 0
    return (url: string) => {
        if (url.endsWith('/oauth/device-authorization/')) {
            return { status: 200, body: DEVICE }
        }
        if (url.endsWith('/oauth/revoke/')) {
            return { status: 200, body: {} }
        }
        if (url.endsWith('/api/personal_api_keys/@current/')) {
            return { status: 200, body: { scopes: ['query:read'] } }
        }
        return polls++ < pendingPolls ? { status: 400, body: { error: 'authorization_pending' } } : final
    }
}

describe('hog auth login', () => {
    test('an agent gets a link to hand over, without blocking or seeing the device code', async () => {
        const result = await runHog(['auth', 'login', '--region', 'eu'], {
            env: { CLAUDECODE: '1' },
            respond: deviceFlow(0),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            status: 'pending',
            code: 'BCDF-GHJK',
            url: `${EU}/device?code=BCDF-GHJK`,
            next: 'hog auth login --wait',
        })
        expect(result.stdout).not.toContain(DEVICE_CODE)
        expect(readJson(result.files[PENDING_FILE] ?? '{}')).toMatchObject({ deviceCode: DEVICE_CODE })
        expect(result.opened).toEqual([])
        expect(result.requests).toEqual([
            {
                method: 'POST',
                url: `${EU}/oauth/device-authorization/`,
                body: { client_id: HOG_CLIENT_ID, scope: LOGIN_SCOPES.join(' ') },
            },
        ])
    })

    test('--read-only asks for read access only', async () => {
        const result = await runHog(['auth', 'login', '--region', 'eu', '--read-only'], {
            env: { CLAUDECODE: '1' },
            respond: deviceFlow(0),
        })

        const requested = String((result.requests[0]?.body as { scope?: string } | undefined)?.scope ?? '').split(' ')
        expect(requested).toContain('insight:read')
        expect(requested).toContain('openid')
        expect(requested.filter((scope) => scope.endsWith(':write'))).toEqual([])
    })

    test('an approval link on another origin than the host is replaced with the page on the host', async () => {
        const result = await runHog(['auth', 'login', '--region', 'eu'], {
            env: { CLAUDECODE: '1' },
            respond: () => ({
                status: 200,
                body: {
                    ...DEVICE,
                    verification_uri: 'https://phish.example.com/device',
                    verification_uri_complete: 'https://phish.example.com/device?code=BCDF-GHJK',
                },
            }),
        })

        expect(result.json()).toMatchObject({ status: 'pending', url: `${EU}/device?code=BCDF-GHJK` })
    })

    test.each([
        ['a posthog.json Cloud host picks the region', [], EU, EU],
        ['--region beats the posthog.json host', ['--region', 'eu'], 'https://us.posthog.com', EU],
    ])('%s', async (_name, flags, configHost, loginHost) => {
        const result = await runHog(['auth', 'login', ...flags], {
            env: { CLAUDECODE: '1' },
            files: { '/work/posthog.json': JSON.stringify({ host: configHost }) },
            respond: deviceFlow(0),
        })

        expect(result.exitCode).toBe(0)
        expect(result.requests.map((request) => request.url)).toEqual([`${loginHost}/oauth/device-authorization/`])
    })

    test('a posthog.json host outside PostHog Cloud never starts a login', async () => {
        const result = await runHog(['auth', 'login'], {
            env: { CLAUDECODE: '1' },
            files: { '/work/posthog.json': JSON.stringify({ host: 'https://login.example.com' }) },
            respond: deviceFlow(0),
        })

        expect(result.error()).toMatchObject({ code: 'region_required' })
        expect(result.requests).toEqual([])
    })

    test('an agent that retries gets the same code, so the link it shared keeps working', async () => {
        const result = await runHog(['auth', 'login', '--region', 'eu'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(0),
        })
        expect(result.json()).toMatchObject({ status: 'pending', code: 'BCDF-GHJK' })
        expect(result.requests).toEqual([])
    })

    test.each([
        ['an agent without a region', ['auth', 'login'], { CLAUDECODE: '1' }, {}, 2, 'region_required'],
        ['a CI job', ['auth', 'login', '--region', 'us'], { CI: 'true' }, {}, 1, 'login_needs_a_person'],
        ['--wait with no login started', ['auth', 'login', '--wait'], { CLAUDECODE: '1' }, {}, 1, 'no_pending_login'],
        [
            '--read-only with --wait',
            ['auth', 'login', '--wait', '--read-only'],
            { CLAUDECODE: '1' },
            { [PENDING_FILE]: PENDING },
            2,
            'read_only_with_wait',
        ],
    ])('%s fails with a hint', async (_name, argv, env, files, exitCode, code) => {
        const result = await runHog(argv, { env, files, respond: deviceFlow(0) })
        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })

    test('--wait stores only the scopes the person approved', async () => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(0, { status: 200, body: { ...APPROVED, scope: 'openid insight:read' } }),
        })

        expect(result.json()).toMatchObject({ status: 'logged_in', scopes: ['openid', 'insight:read'] })
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toMatchObject({
            logins: { [EU]: { '42': { scopes: ['openid', 'insight:read'] } } },
        })
    })

    test('--wait stores the token for the approved project in the keychain', async () => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(2),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            status: 'logged_in',
            host: EU,
            projectId: '42',
            scopes: LOGIN_SCOPES,
            expiresAt: expect.any(String),
        })
        expect(result.stdout).not.toContain(ACCESS_TOKEN)
        // The keychain keeps only the tokens. What isn't secret is in settings.json.
        expect(readJson(result.keychain[EU_ITEM] ?? '{}')).toEqual({
            accessToken: ACCESS_TOKEN,
            refreshToken: REFRESH_TOKEN,
        })
        // Windows Credential Manager refuses an item over 2,560 bytes, and Bun stores it as UTF-8.
        expect(Buffer.byteLength(result.keychain[EU_ITEM] ?? '')).toBeLessThanOrEqual(2560)
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toEqual({
            logins: {
                [EU]: {
                    '42': {
                        store: 'keychain',
                        type: 'oauth',
                        projectId: '42',
                        host: EU,
                        expiresAt: expect.any(Number),
                        scopes: LOGIN_SCOPES,
                        loginId: expect.any(String),
                        loggedInAt: expect.any(Number),
                    },
                },
            },
        })
        expect(result.files[LEGACY_CLI_FILE]).toBeUndefined()
        expect(result.files[PENDING_FILE]).toBeUndefined()
        expect(result.requests.filter((request) => request.url.endsWith('/oauth/token/'))).toHaveLength(3)
    })

    const denied = Object.assign(new Error('User canceled'), { code: 'ERR_SECRETS_USER_CANCELED' })
    test.each([
        [
            'is unavailable',
            Object.assign(new Error('no Secret Service'), { code: 'ERR_SECRETS_PLATFORM_ERROR' }),
            false,
        ],
        ['is denied', denied, false],
        // An item an older hog build saved can ask again even though a new probe item works.
        ["denies the host's item after the probe passes", denied, true],
    ])(
        'a login saves the token in a private file, and says so, when the keychain %s',
        async (_name, failure, probeWorks) => {
            const items = new Map<string, string>()
            const check = (name: string): void => {
                if (!probeWorks || name.startsWith('https://')) {
                    throw failure
                }
            }
            const broken: Secrets = {
                get: async (name) => {
                    check(name)
                    return items.get(name) ?? null
                },
                set: async (name, value) => {
                    check(name)
                    items.set(name, value)
                },
                delete: async (name) => {
                    check(name)
                    return items.delete(name)
                },
            }
            const result = await runHog(['auth', 'login', '--wait'], {
                env: { CLAUDECODE: '1' },
                files: { [PENDING_FILE]: PENDING },
                respond: deviceFlow(0),
                secrets: () => broken,
            })

            expect(result.exitCode).toBe(0)
            expect(result.json()).toMatchObject({
                store: 'file',
                credentialsPath: HOG_CREDENTIALS_FILE,
                keychainError: expect.stringContaining('keychain'),
            })
            expect(readJson(result.files[HOG_CREDENTIALS_FILE] ?? '{}')).toEqual({
                [EU_ITEM]: { accessToken: ACCESS_TOKEN, refreshToken: REFRESH_TOKEN },
            })
            expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toMatchObject({
                logins: { [EU]: { '42': { store: 'file', projectId: '42' } } },
            })
        }
    )

    test.each([
        [
            'stops when the code expires and forgets it',
            { status: 400, body: { error: 'expired_token' } },
            { code: 'login_expired' },
            false,
        ],
        [
            'stops when the person denies it and forgets it',
            { status: 400, body: { error: 'access_denied' } },
            { code: 'login_rejected' },
            false,
        ],
        [
            "stops with PostHog's reason when it refuses the client, and forgets it",
            {
                status: 400,
                body: { error: 'unauthorized_client', error_description: "PostHog hasn't verified this app." },
            },
            { code: 'login_unavailable', message: expect.stringContaining("hasn't verified this app") },
            false,
        ],
        [
            'retries a server that keeps failing, then keeps the login to resume',
            { status: 503, body: 'Service Unavailable' },
            { code: 'login_interrupted' },
            true,
        ],
    ])('--wait %s', async (_name, final, expected, keepsPending) => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(1, final),
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject(expected)
        expect(result.files[PENDING_FILE] !== undefined).toBe(keepsPending)
        expect(result.keychain).toEqual({})
    })

    test.each([
        ['approving in the browser', ['eu'], true, EU, { accessToken: ACCESS_TOKEN }],
        [
            'pasting a personal API key',
            ['key', 'https://ph.example.com/', '42', 'phx_secret'],
            false,
            'https://ph.example.com',
            { apiKey: 'phx_secret' },
        ],
    ])('a person at a terminal logs in by %s', async (_name, answers, opensBrowser, host, secret) => {
        const result = await runHog(['auth', 'login'], {
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
            files: { [PENDING_FILE]: PENDING },
            answers,
            respond: deviceFlow(1),
        })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain(`Logged in to ${host}, project 42.`)
        expect(result.opened).toHaveLength(opensBrowser ? 1 : 0)
        expect(result.files[PENDING_FILE]).toBeUndefined()
        expect(readJson(result.keychain[`${host}#42`] ?? '{}')).toMatchObject(secret)
        expect(result.stdout).toContain('Try it: hog query run')
    })

    test('a pasted personal API key that PostHog rejects is not saved', async () => {
        const result = await runHog(['auth', 'login'], {
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
            answers: ['key', 'https://ph.example.com/', '42', 'phx_deleted'],
            respond: () => ({ status: 401, body: { detail: 'Invalid personal API key.' } }),
        })

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain('https://ph.example.com rejected the personal API key')
        expect(result.keychain).toEqual({})
    })

    const STORED = JSON.stringify({ host: 'https://eu.posthog.com', token: 'phx_secret', env_id: '42' })
    const KEYCHAIN_LOGIN = {
        files: { [SETTINGS_FILE]: settingsJson(EU, keyRecord(EU)) },
        keychain: { [EU_ITEM]: JSON.stringify({ apiKey: 'phx_secret' }) },
    }
    const OAUTH_RECORD = {
        store: 'keychain',
        type: 'oauth',
        projectId: '42',
        host: EU,
        expiresAt: Date.UTC(2026, 0, 2),
        scopes: ['openid', 'insight:read'],
        loginId: 'login-1',
    }
    const OAUTH_LOGIN = {
        files: { [SETTINGS_FILE]: settingsJson(EU, OAUTH_RECORD) },
        keychain: { [EU_ITEM]: JSON.stringify({ accessToken: ACCESS_TOKEN, refreshToken: REFRESH_TOKEN }) },
    }

    // A monorepo whose apps use two projects on one host. Project 2 is the latest login there, and
    // project 9 is the only login to the US host.
    const MONOREPO = {
        files: {
            '/repo/.git/HEAD': 'ref: refs/heads/main\n',
            '/repo/apps/web/posthog.json': JSON.stringify({ host: EU, projectId: 1 }),
            '/repo/apps/api/posthog.json': JSON.stringify({ host: EU, projectId: 2 }),
            '/repo/apps/docs/posthog.json': JSON.stringify({ host: EU, projectId: 3 }),
            '/repo/apps/admin/posthog.json': JSON.stringify({ host: EU, projectId: '01' }),
            [SETTINGS_FILE]: settingsJson(
                EU,
                { ...keyRecord(EU, 'keychain', '1'), loggedInAt: 1 },
                { ...keyRecord(EU, 'keychain', '2'), loggedInAt: 2 },
                keyRecord(US, 'keychain', '9')
            ),
        },
        keychain: {
            [`${EU}#1`]: JSON.stringify({ apiKey: 'phx_one' }),
            [`${EU}#2`]: JSON.stringify({ apiKey: 'phx_two' }),
            [`${US}#9`]: JSON.stringify({ apiKey: 'phx_nine' }),
        },
    }
    test.each([
        ['/repo/apps/web', 1],
        ['/repo/apps/api', 2],
        ['/repo/apps/admin', 1],
    ])('a command in %s uses the login for the project its posthog.json names', async (cwd, project) => {
        const result = await runHog(['query', 'run', 'select 1'], {
            env: { CLAUDECODE: '1' },
            cwd,
            ...MONOREPO,
            respond: () => ({ status: 200, body: ROWS }),
        })

        expect(result.exitCode).toBe(0)
        expect(result.requests.map((request) => request.url)).toEqual([`${EU}/api/environments/${project}/query`])
    })

    test('a command fails without a request when posthog.json names a project hog has no login for', async () => {
        const result = await runHog(['query', 'run', 'select 1'], {
            env: { CLAUDECODE: '1' },
            cwd: '/repo/apps/docs',
            ...MONOREPO,
            respond: () => ({ status: 200, body: ROWS }),
        })

        expect(result.exitCode).toBe(2)
        expect(result.error()).toMatchObject({
            code: 'project_mismatch',
            message: expect.stringContaining(
                `/repo/apps/docs/posthog.json names project 3, but you aren't logged in to it on ${EU}`
            ),
            hint: expect.stringContaining(`hog auth login --host ${EU}`),
        })
        expect(result.requests).toEqual([])
    })

    test.each([
        [
            'posthog.json names the host and project',
            [],
            {},
            '/repo/apps/web',
            { projectId: '1', config: '/repo/apps/web/posthog.json', login: { match: 'exact', projectId: '1' } },
        ],
        [
            'HOG_PROJECT_ID replaces the project in posthog.json',
            [],
            { HOG_PROJECT_ID: '1' },
            '/repo/apps/api',
            { projectId: '1', login: { match: 'override', reason: expect.stringContaining('HOG_PROJECT_ID') } },
        ],
        [
            '--host replaces the host in posthog.json',
            ['--host', `${EU}/`],
            {},
            '/repo/apps/api',
            { projectId: '2', login: { match: 'override', reason: expect.stringContaining('--host') } },
        ],
        [
            '--host names another host than posthog.json, whose project is then left out',
            ['--host', US],
            {},
            '/repo/apps/api',
            { projectId: '9', login: { match: 'fallback', reason: expect.stringContaining('on another host') } },
        ],
        [
            'nothing names a project, so the latest login is used',
            [],
            {},
            '/repo',
            { projectId: '2', config: null, login: { match: 'fallback', projectId: null } },
        ],
        [
            'posthog.json names a project hog has no login for',
            [],
            {},
            '/repo/apps/docs',
            {
                authenticated: false,
                projectId: '3',
                config: '/repo/apps/docs/posthog.json',
                next: `hog auth login --host ${EU}`,
            },
        ],
    ])('status explains the login it picks when %s', async (_name, flags, env, cwd, expected) => {
        const result = await runHog(['auth', 'status', ...flags], {
            env: { CLAUDECODE: '1', ...env },
            cwd,
            ...MONOREPO,
            respond: () => ({ status: 200, body: { email: 'ana@example.com', name: 'Shop' } }),
        })

        expect(result.json()).toMatchObject(expected)
    })

    test('status tells a person which posthog.json picked the login and why', async () => {
        const result = await runHog(['auth', 'status'], {
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
            cwd: '/repo/apps/web',
            ...MONOREPO,
            respond: () => ({ status: 200, body: { email: 'ana@example.com', name: 'Web' } }),
        })

        expect(result.stdout).toContain('Project: Web (1)')
        expect(result.stdout).toContain('Config: /repo/apps/web/posthog.json')
        expect(result.stdout).toContain('Login picked because posthog.json sets the host and the project.')
    })

    test.each([
        [
            'creates posthog.json in this folder when none is above it',
            {},
            '/repo/apps/api/posthog.json',
            'created',
            { $schema: expect.any(String), host: EU, projectId: 7 },
        ],
        [
            'sets the pair in the closest posthog.json above, keeping its other settings',
            { '/repo/posthog.json': JSON.stringify({ host: EU, projectId: 42, endpoints: { dir: 'endpoints' } }) },
            '/repo/posthog.json',
            'updated',
            { host: EU, projectId: 7, endpoints: { dir: 'endpoints' } },
        ],
        [
            'leaves a posthog.json that already names the pair',
            { '/repo/apps/api/posthog.json': JSON.stringify({ projectId: '7', host: `${EU}/` }) },
            '/repo/apps/api/posthog.json',
            'unchanged',
            { projectId: '7', host: `${EU}/` },
        ],
    ])('a login to a second project keeps the first, and %s', async (_name, files, path, status, config) => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            cwd: '/repo/apps/api',
            files: { ...KEYCHAIN_LOGIN.files, ...files, '/repo/.git/HEAD': 'ref', [PENDING_FILE]: PENDING },
            keychain: KEYCHAIN_LOGIN.keychain,
            respond: deviceFlow(0, { status: 200, body: { ...APPROVED, scoped_teams: [7] } }),
        })

        expect(result.json()).toMatchObject({ status: 'logged_in', projectId: '7', config: { path, status } })
        expect(readJson(result.files[path] ?? '{}')).toEqual(config)
        expect(result.keychain[EU_ITEM]).toBe(KEYCHAIN_LOGIN.keychain[EU_ITEM])
        expect(readJson(result.keychain[`${EU}#7`] ?? '{}')).toMatchObject({ accessToken: ACCESS_TOKEN })
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toMatchObject({
            logins: { [EU]: { '7': { type: 'oauth' }, '42': { type: 'personal_api_key' } } },
        })
    })

    test('logout removes only the login posthog.json picks, and says which', async () => {
        const result = await runHog(['auth', 'logout'], {
            env: { CLAUDECODE: '1' },
            cwd: '/repo/apps/api',
            ...MONOREPO,
        })

        expect(result.json()).toMatchObject({ status: 'logged_out', host: EU, projectId: '2', logins: null })
        const { [`${EU}#2`]: _removed, ...kept } = MONOREPO.keychain
        expect(result.keychain).toEqual(kept)
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toEqual({
            logins: {
                [EU]: { '1': { ...keyRecord(EU, 'keychain', '1'), loggedInAt: 1 } },
                [US]: { '9': keyRecord(US, 'keychain', '9') },
            },
        })
    })

    test('a login in the shape that kept one login per host works, and moves under its project', async () => {
        const result = await runHog(['auth', 'status'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: JSON.stringify({
                    logins: { [EU]: { ...OAUTH_RECORD, expiresAt: Date.UTC(2026, 0, 1) } },
                    host: EU,
                }),
            },
            keychain: { [EU]: OAUTH_LOGIN.keychain[EU_ITEM] },
            respond: (url) =>
                url.endsWith('/oauth/token/')
                    ? { status: 200, body: { access_token: STEPPED_UP_ACCESS, expires_in: 3600 } }
                    : { status: 200, body: { email: 'ana@example.com', name: 'Shop' } },
        })

        expect(result.json()).toMatchObject({ authenticated: true, projectId: '42', login: { match: 'fallback' } })
        expect(Object.keys(result.keychain)).toEqual([EU_ITEM])
        expect(readJson(result.keychain[EU_ITEM] ?? '{}')).toEqual({
            accessToken: STEPPED_UP_ACCESS,
            refreshToken: REFRESH_TOKEN,
        })
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toEqual({
            logins: { [EU]: { '42': { ...OAUTH_RECORD, expiresAt: Date.UTC(2026, 0, 1) + 3_600_000 } } },
            host: EU,
        })
    })

    test.each([
        [
            'a working key',
            200,
            200,
            0,
            { authenticated: true, user: { email: 'ana@example.com' }, projectName: 'Shop' },
        ],
        ['a key without user:read', 403, 200, 0, { authenticated: true, user: null, projectName: 'Shop' }],
        ['a deleted key', 401, 401, 1, { authenticated: false, error: expect.any(String), next: 'hog auth login' }],
    ])('status reports %s', async (_name, userStatus, projectStatus, exitCode, expected) => {
        const result = await runHog(['auth', 'status'], {
            env: { CLAUDECODE: '1' },
            ...KEYCHAIN_LOGIN,
            respond: (url) =>
                url.endsWith('/api/users/@me/')
                    ? { status: userStatus, body: { email: 'ana@example.com' } }
                    : { status: projectStatus, body: { name: 'Shop' } },
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.json()).toMatchObject({ host: 'https://eu.posthog.com', projectId: '42', ...expected })
        expect(result.stdout).not.toContain('phx_secret')
    })

    test.each([
        ['a hog login', KEYCHAIN_LOGIN, { source: 'store', store: 'keychain', credentialsPath: null }],
        [
            'an OAuth login',
            OAUTH_LOGIN,
            {
                kind: 'oauth',
                source: 'store',
                store: 'keychain',
                scopes: ['openid', 'insight:read'],
                expiresAt: '2026-01-02T00:00:00.000Z',
            },
        ],
    ])(
        'status names where the credentials of %s come from, and what they can do',
        async (_name, { files, keychain }, expected) => {
            const result = await runHog(['auth', 'status'], {
                env: { CLAUDECODE: '1' },
                files,
                keychain,
                respond: () => ({ status: 200, body: { email: 'ana@example.com', name: 'Shop' } }),
            })
            expect(result.json()).toMatchObject({ authenticated: true, ...expected })
        }
    )

    test('status escapes terminal control characters in the project name', async () => {
        const result = await runHog(['auth', 'status'], {
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
            ...KEYCHAIN_LOGIN,
            respond: (url) =>
                url.endsWith('/api/users/@me/')
                    ? { status: 200, body: { email: 'ana@example.com' } }
                    : { status: 200, body: { name: '\u001b]52;c;eA==\u0007Shop' } },
        })
        expect(result.stdout).toContain('Project: \\x1b]52;c;eA==\\x07Shop (42)')
        expect(result.stdout).not.toContain('\u001b')
    })

    test('status fails when one request lacks a scope and the other fails', async () => {
        const result = await runHog(['auth', 'status'], {
            env: { CLAUDECODE: '1' },
            ...KEYCHAIN_LOGIN,
            respond: (url) => (url.endsWith('/api/users/@me/') ? { status: 403, body: {} } : { status: 500, body: {} }),
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'http_500' })
    })

    test('status without a key exits 1 and points to login', async () => {
        const result = await runHog(['auth', 'status'], { env: { CLAUDECODE: '1' } })
        expect(result.exitCode).toBe(1)
        expect(result.json()).toEqual({ authenticated: false, next: 'hog auth login', config: null, login: null })
    })

    test.each([
        [
            'a stored key',
            { ...KEYCHAIN_LOGIN.files, [PENDING_FILE]: PENDING },
            {},
            'logged_out',
            'https://eu.posthog.com/settings/user-api-keys',
            [],
        ],
        ['no stored key', {}, {}, 'not_logged_in', null, []],
        [
            'a file login whose file entry is gone, but whose old keychain item is still there',
            {
                [SETTINGS_FILE]: withPendingRemovals(settingsJson(EU, keyRecord(EU, 'file')), {
                    store: 'keychain',
                    host: EU,
                    projectId: '42',
                }),
            },
            {},
            'logged_out',
            null,
            [],
        ],
        [
            'a posthog.json host that is not the last login',
            {
                [SETTINGS_FILE]: settingsJson(US, keyRecord(EU), keyRecord(US)),
                '/work/posthog.json': JSON.stringify({ host: 'https://eu.posthog.com' }),
            },
            {},
            'logged_out',
            'https://eu.posthog.com/settings/user-api-keys',
            [],
        ],
        [
            "a key in the environment and posthog-cli's file, which hog leaves alone",
            { ...KEYCHAIN_LOGIN.files, [LEGACY_CLI_FILE]: STORED },
            { HOG_PERSONAL_API_KEY: 'phx_env' },
            'logged_out',
            'https://eu.posthog.com/settings/user-api-keys',
            ['HOG_PERSONAL_API_KEY'],
        ],
    ])(
        'logout with %s removes what hog stored',
        async (_name, files: Record<string, string>, env, status, revokeUrl, stillSet) => {
            const result = await runHog(['auth', 'logout'], {
                env: { CLAUDECODE: '1', ...env },
                files,
                keychain: KEYCHAIN_LOGIN.keychain,
            })
            expect(result.requests).toEqual([])
            expect(result.exitCode).toBe(0)
            expect(result.json()).toMatchObject({ status, revokeUrl, stillSet })
            expect(result.keychain).toEqual(files[SETTINGS_FILE] ? {} : KEYCHAIN_LOGIN.keychain)
            expect(result.files[PENDING_FILE]).toBeUndefined()
            expect(result.files[LEGACY_CLI_FILE]).toBe(files[LEGACY_CLI_FILE])
        }
    )

    test.each([
        ['a personal API key without the phx_ prefix', KEYCHAIN_LOGIN.files, { apiKey: 'unprefixedkey123' }, null],
        [
            'an OAuth login without token prefixes, which it says it could not revoke',
            OAUTH_LOGIN.files,
            { accessToken: 'legacyaccess', refreshToken: 'legacyrefresh' },
            false,
        ],
    ])('logout removes a stored key hog can no longer read: %s', async (_name, files, secret, revoked) => {
        const result = await runHog(['auth', 'logout'], {
            env: { CLAUDECODE: '1' },
            files,
            keychain: { [EU_ITEM]: JSON.stringify(secret) },
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ status: 'logged_out', revoked })
        expect(result.requests).toEqual([])
        expect(result.keychain).toEqual({})
    })

    test.each([
        ['revokes an OAuth login in PostHog before it removes it', 200, true],
        ['says when PostHog could not revoke the login, and still removes it', 503, false],
    ])('logout %s', async (_name, status, revoked) => {
        const result = await runHog(['auth', 'logout'], {
            env: { CLAUDECODE: '1' },
            ...OAUTH_LOGIN,
            respond: () => ({ status, body: {} }),
        })

        expect(result.json()).toMatchObject({ status: 'logged_out', revoked, revokeUrl: null })
        expect(result.requests).toEqual([
            {
                method: 'POST',
                url: `${EU}/oauth/revoke/`,
                body: { token: REFRESH_TOKEN, token_type_hint: 'refresh_token', client_id: HOG_CLIENT_ID },
            },
        ])
        expect(result.keychain).toEqual({})
    })

    // A keychain that refuses every write and removal until `works.now` is true.
    function flakyKeychain(items: Map<string, string>): { secrets: Secrets; works: { now: boolean } } {
        const keychainWorks = { now: false }
        const secrets: Secrets = {
            get: async (name) => items.get(name) ?? null,
            set: async (name, value) => {
                if (!keychainWorks.now) {
                    throw Object.assign(new Error('denied'), { code: 'ERR_SECRETS_USER_CANCELED' })
                }
                items.set(name, value)
            },
            delete: async (name) => {
                if (!keychainWorks.now) {
                    throw Object.assign(new Error('denied'), { code: 'ERR_SECRETS_USER_CANCELED' })
                }
                return items.delete(name)
            },
        }
        return { secrets, works: keychainWorks }
    }

    const KEYCHAIN_LOGINS = [
        ['a keychain login', KEYCHAIN_LOGIN.files, EU_ITEM],
        [
            'a keychain login stored in the shape that kept one login per host',
            { [SETTINGS_FILE]: JSON.stringify({ logins: { [EU]: keyRecord(EU) }, host: EU }) },
            EU,
        ],
    ] as const

    test('a command moves only the old-shape login it uses, so a keychain login to another host stays untouched', async () => {
        const keychainCalls: string[] = []
        const result = await runHog(['query', 'run', 'select 1'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: JSON.stringify({
                    logins: { [EU]: keyRecord(EU), [US]: keyRecord(US, 'file') },
                    host: US,
                }),
                [HOG_CREDENTIALS_FILE]: JSON.stringify({ [US]: { apiKey: 'phx_us' } }),
            },
            secrets: () => ({
                get: async (name) => {
                    keychainCalls.push(name)
                    return null
                },
                set: async (name) => {
                    keychainCalls.push(name)
                },
                delete: async (name) => {
                    keychainCalls.push(name)
                    return false
                },
            }),
            respond: () => ({ status: 200, body: ROWS }),
        })

        expect(result.exitCode).toBe(0)
        expect(keychainCalls).toEqual([])
        expect(readJson(result.files[HOG_CREDENTIALS_FILE] ?? '{}')).toEqual({ [`${US}#42`]: { apiKey: 'phx_us' } })
    })

    test('a login in the old shape stays usable when its secret cannot move, and moves on a later run', async () => {
        const items = new Map([[EU, JSON.stringify({ apiKey: 'phx_secret' })]])
        const writes = { refused: true }
        const secrets: Secrets = {
            get: async (name) => items.get(name) ?? null,
            set: async (name, value) => {
                if (writes.refused) {
                    throw Object.assign(new Error('denied'), { code: 'ERR_SECRETS_USER_CANCELED' })
                }
                items.set(name, value)
            },
            delete: async (name) => items.delete(name),
        }
        const query = {
            env: { CLAUDECODE: '1' },
            secrets: () => secrets,
            respond: () => ({ status: 200, body: ROWS }),
        }
        const refused = await runHog(['query', 'run', 'select 1'], {
            ...query,
            files: { [SETTINGS_FILE]: JSON.stringify({ logins: { [EU]: keyRecord(EU) }, host: EU }) },
        })
        expect(refused.exitCode).toBe(0)
        expect([...items.keys()]).toEqual([EU])

        writes.refused = false
        const moved = await runHog(['query', 'run', 'select 1'], { ...query, files: refused.files })

        expect(moved.exitCode).toBe(0)
        expect([...items.keys()]).toEqual([EU_ITEM])
        expect(readJson(moved.files[SETTINGS_FILE] ?? '{}')).toEqual({
            logins: { [EU]: { '42': keyRecord(EU) } },
            host: EU,
        })
    })

    test('a login that the keychain refused to remove from under its host goes on the next logout', async () => {
        const items = new Map([[EU, JSON.stringify({ apiKey: 'phx_old' })]])
        const deletes = { refused: true }
        const secrets: Secrets = {
            get: async (name) => items.get(name) ?? null,
            set: async (name, value) => {
                items.set(name, value)
            },
            delete: async (name) => {
                if (deletes.refused && name === EU) {
                    throw Object.assign(new Error('denied'), { code: 'ERR_SECRETS_USER_CANCELED' })
                }
                return items.delete(name)
            },
        }
        const login = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: JSON.stringify({ logins: { [EU]: keyRecord(EU) }, host: EU }),
                [PENDING_FILE]: PENDING,
            },
            respond: deviceFlow(0),
            secrets: () => secrets,
        })
        expect(login.json()).toMatchObject({ store: 'keychain' })
        expect(items.has(EU)).toBe(true)

        deletes.refused = false
        const logout = await runHog(['auth', 'logout'], {
            env: { CLAUDECODE: '1' },
            files: login.files,
            respond: deviceFlow(0),
            secrets: () => secrets,
        })

        expect(logout.json()).toMatchObject({ status: 'logged_out', keychainLeftover: null })
        expect([...items.keys()]).toEqual([])
    })

    test.each(KEYCHAIN_LOGINS)(
        'a file login that replaced %s takes the old keychain item with it on logout',
        async (_name, files, item) => {
            const oldItem = JSON.stringify({ apiKey: 'phx_old' })
            const items = new Map<string, string>([[item, oldItem]])
            const { secrets, works: keychainWorks } = flakyKeychain(items)
            const login = await runHog(['auth', 'login', '--wait'], {
                env: { CLAUDECODE: '1' },
                files: { ...files, [PENDING_FILE]: PENDING },
                respond: deviceFlow(0),
                secrets: () => secrets,
            })
            expect(login.json()).toMatchObject({ store: 'file' })

            const denied = await runHog(['auth', 'logout'], {
                env: { CLAUDECODE: '1' },
                files: login.files,
                secrets: () => secrets,
            })
            expect(denied.json()).toMatchObject({
                status: 'logged_out',
                keychainLeftover: expect.stringContaining('keychain'),
            })
            expect(items.get(item)).toBe(oldItem)

            keychainWorks.now = true
            const removed = await runHog(['auth', 'logout'], {
                env: { CLAUDECODE: '1' },
                files: login.files,
                secrets: () => secrets,
            })
            expect(removed.json()).toMatchObject({ status: 'logged_out', keychainLeftover: null })
            expect(items.size).toBe(0)
        }
    )

    test.each(KEYCHAIN_LOGINS)(
        'a keychain login that replaces a file login, which replaced %s, takes the old keychain item',
        async (_name, files, item) => {
            const items = new Map<string, string>([[item, JSON.stringify({ apiKey: 'phx_old' })]])
            const { secrets, works } = flakyKeychain(items)
            const login = { env: { CLAUDECODE: '1' }, respond: deviceFlow(0), secrets: () => secrets }
            const fileLogin = await runHog(['auth', 'login', '--wait'], {
                ...login,
                files: { ...files, [PENDING_FILE]: PENDING },
            })
            expect(fileLogin.json()).toMatchObject({ store: 'file' })

            works.now = true
            const keychainLogin = await runHog(['auth', 'login', '--wait'], {
                ...login,
                files: { ...fileLogin.files, [PENDING_FILE]: PENDING },
            })

            expect(keychainLogin.json()).toMatchObject({ store: 'keychain' })
            expect([...items.keys()]).toEqual([EU_ITEM])
            expect(readJson(items.get(EU_ITEM) ?? '{}')).toMatchObject({ accessToken: ACCESS_TOKEN })
            expect(keychainLogin.files[HOG_CREDENTIALS_FILE]).toBeUndefined()
        }
    )

    test('logout --all removes every login, and the leftovers settings.json no longer names', async () => {
        const ORPHAN = 'https://posthog.example.com'
        const result = await runHog(['auth', 'logout', '--all'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: withPendingRemovals(
                    settingsJson(US, keyRecord(EU), keyRecord(EU, 'keychain', '7'), keyRecord(US, 'file')),
                    { store: 'keychain', host: US, projectId: '42' }
                ),
                [HOG_CREDENTIALS_FILE]: JSON.stringify({
                    [`${US}#42`]: { apiKey: 'phx_us' },
                    [`${ORPHAN}#5`]: { apiKey: 'phx_orphan' },
                    // A secret filed under its host alone, which settings.json no longer names.
                    [ORPHAN]: { apiKey: 'phx_orphan_host' },
                    // An older hog keyed `localhost:8000` by its origin, which is "null".
                    null: { apiKey: 'phx_unreadable' },
                }),
                [PENDING_FILE]: PENDING,
            },
            keychain: {
                ...KEYCHAIN_LOGIN.keychain,
                [`${EU}#7`]: JSON.stringify({ apiKey: 'phx_seven' }),
                [`${US}#42`]: JSON.stringify({ apiKey: 'phx_before_fallback' }),
                [ORPHAN]: JSON.stringify({ apiKey: 'phx_before_settings_were_lost' }),
            },
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            status: 'logged_out',
            logins: [
                { host: EU, projectId: '7', revokeUrl: `${EU}/settings/user-api-keys` },
                { host: EU, projectId: '42', revokeUrl: `${EU}/settings/user-api-keys` },
                { host: US, projectId: '42', revokeUrl: `${US}/settings/user-api-keys` },
                { host: ORPHAN, projectId: '5', revokeUrl: null },
                { host: ORPHAN, projectId: null, revokeUrl: null },
            ],
        })
        expect(result.keychain).toEqual({})
        expect(result.files[HOG_CREDENTIALS_FILE]).toBeUndefined()
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toEqual({ logins: {} })
        expect(result.files[PENDING_FILE]).toBeUndefined()
    })

    test('logout of a keychain login in the old shape removes the copy an older hog left in the credentials file', async () => {
        const result = await runHog(['auth', 'logout'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: JSON.stringify({ logins: { [EU]: keyRecord(EU) }, host: EU }),
                [HOG_CREDENTIALS_FILE]: JSON.stringify({ [EU]: { apiKey: 'phx_secret' } }),
            },
            keychain: { [EU]: JSON.stringify({ apiKey: 'phx_secret' }) },
        })

        expect(result.json()).toMatchObject({ status: 'logged_out', projectId: '42' })
        expect(result.keychain).toEqual({})
        expect(result.files[HOG_CREDENTIALS_FILE]).toBeUndefined()
    })

    test('logout --all revokes the logins it removed before a later keychain read fails', async () => {
        const items = new Map([
            [`${EU}#7`, JSON.stringify({ accessToken: ACCESS_TOKEN, refreshToken: REFRESH_TOKEN })],
            [EU_ITEM, JSON.stringify({ accessToken: ACCESS_TOKEN, refreshToken: STEPPED_UP_REFRESH })],
        ])
        const result = await runHog(['auth', 'logout', '--all'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: settingsJson(
                    EU,
                    { ...OAUTH_RECORD, projectId: '7', loginId: 'login-7' },
                    OAUTH_RECORD
                ),
            },
            secrets: () => ({
                get: async (name) => {
                    if (name === EU_ITEM) {
                        throw Object.assign(new Error('denied'), { code: 'ERR_SECRETS_USER_CANCELED' })
                    }
                    return items.get(name) ?? null
                },
                set: async (name, value) => {
                    items.set(name, value)
                },
                delete: async (name) => items.delete(name),
            }),
            respond: deviceFlow(0),
        })

        expect(result.error()).toMatchObject({ code: 'keychain_access_denied' })
        const revoked = result.requests
            .filter((request) => request.url.endsWith('/oauth/revoke/'))
            .map((request) => (request.body as { token?: string }).token)
        expect(revoked).toEqual([REFRESH_TOKEN])
        expect([...items.keys()]).toEqual([EU_ITEM])
    })

    test('a login in the old shape is the fallback again once a newer login to another host logs out', async () => {
        const files = {
            [SETTINGS_FILE]: JSON.stringify({
                logins: { [EU]: keyRecord(EU), [US]: { '7': { ...keyRecord(US, 'keychain', '7'), loggedInAt: 1 } } },
                host: EU,
            }),
        }
        const keychain = {
            [EU]: JSON.stringify({ apiKey: 'phx_eu' }),
            [`${US}#7`]: JSON.stringify({ apiKey: 'phx_us' }),
        }
        const logout = await runHog(['auth', 'logout'], { env: { CLAUDECODE: '1' }, files, keychain })
        expect(logout.json()).toMatchObject({ status: 'logged_out', host: US, projectId: '7' })

        const status = await runHog(['auth', 'status'], {
            env: { CLAUDECODE: '1' },
            files: logout.files,
            keychain: logout.keychain,
            respond: () => ({ status: 200, body: { email: 'ana@example.com', name: 'Shop' } }),
        })

        expect(status.json()).toMatchObject({ authenticated: true, host: EU, projectId: '42' })
    })

    test('logout --all revokes a login whose secret could not move from under its host', async () => {
        const PROJECT_7_REFRESH = `phr_${'7'.repeat(43)}`
        const items = new Map([
            [`${EU}#7`, JSON.stringify({ accessToken: ACCESS_TOKEN, refreshToken: PROJECT_7_REFRESH })],
            [EU, OAUTH_LOGIN.keychain[EU_ITEM] ?? ''],
        ])
        const result = await runHog(['auth', 'logout', '--all'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: settingsJson(
                    EU,
                    { ...OAUTH_RECORD, projectId: '7', loginId: 'login-7' },
                    { ...OAUTH_RECORD, storedUnderHost: true }
                ),
            },
            secrets: () => ({
                get: async (name) => items.get(name) ?? null,
                set: async () => {
                    throw Object.assign(new Error('denied'), { code: 'ERR_SECRETS_USER_CANCELED' })
                },
                delete: async (name) => items.delete(name),
            }),
            respond: deviceFlow(0),
        })

        expect(result.json()).toMatchObject({
            logins: [
                { host: EU, projectId: '7', revoked: true },
                { host: EU, projectId: '42', revoked: true },
            ],
        })
        const revoked = result.requests
            .filter((request) => request.url.endsWith('/oauth/revoke/'))
            .map((request) => (request.body as { token?: string }).token)
        expect(revoked).toEqual(expect.arrayContaining([PROJECT_7_REFRESH, REFRESH_TOKEN]))
        expect([...items.keys()]).toEqual([])
    })

    test.each([
        [
            "a key posthog-cli saved moves into the keychain, and posthog-cli's file stays",
            { [LEGACY_CLI_FILE]: STORED },
            200,
            0,
            { status: 'migrated', host: 'https://eu.posthog.com', projectId: '42', store: 'keychain' },
        ],
        [
            'nothing to move points to login',
            {},
            200,
            0,
            { status: 'nothing_to_migrate', legacyFile: LEGACY_CLI_FILE, next: 'hog auth login' },
        ],
        [
            'a broken file fails with a hint',
            { [LEGACY_CLI_FILE]: JSON.stringify({ token: 'abc', env_id: '42' }) },
            200,
            1,
            { code: 'invalid_legacy_credentials', hint: expect.any(String) },
        ],
        [
            'a self-hosted key is checked under the path PostHog sits under',
            {
                [LEGACY_CLI_FILE]: JSON.stringify({
                    host: 'https://example.com/posthog',
                    token: 'phx_secret',
                    env_id: '42',
                }),
            },
            200,
            0,
            { status: 'migrated', host: 'https://example.com/posthog', store: 'keychain' },
        ],
        [
            'a key PostHog rejects stays out of the store',
            { [LEGACY_CLI_FILE]: STORED },
            401,
            1,
            { code: 'key_rejected', hint: expect.stringContaining('hog auth login') },
        ],
    ])('migrate: %s', async (_name, files: Record<string, string>, keyStatus, exitCode, expected) => {
        const result = await runHog(['auth', 'migrate'], {
            env: { CLAUDECODE: '1' },
            files,
            respond: (url) =>
                [
                    'https://eu.posthog.com/api/personal_api_keys/@current/',
                    'https://example.com/posthog/api/personal_api_keys/@current/',
                ].includes(url)
                    ? { status: keyStatus, body: keyStatus === 200 ? { scopes: ['query:read'] } : {} }
                    : { status: 404, body: {} },
        })

        expect(result.exitCode).toBe(exitCode)
        expect(exitCode === 0 ? result.json() : result.error()).toMatchObject(expected)
        expect(result.files[LEGACY_CLI_FILE]).toBe(files[LEGACY_CLI_FILE])
        const migrated = exitCode === 0 && files[LEGACY_CLI_FILE] !== undefined
        expect(Object.values(result.keychain)).toEqual(migrated ? [JSON.stringify({ apiKey: 'phx_secret' })] : [])
    })

    const ADD_PENDING_FILE = '/home/test/.config/hog/pending-auth-add.json'

    test('add asks for the scopes the login has plus the new ones, and keeps the new ones ticked', async () => {
        const result = await runHog(['auth', 'add', 'insight:write', 'dashboard:write'], {
            env: { CLAUDECODE: '1' },
            ...OAUTH_LOGIN,
            respond: deviceFlow(0),
        })

        expect(result.json()).toMatchObject({ status: 'pending', code: 'BCDF-GHJK', next: 'hog auth add --wait' })
        expect(result.requests).toEqual([
            {
                method: 'POST',
                url: `${EU}/oauth/device-authorization/`,
                body: {
                    client_id: HOG_CLIENT_ID,
                    scope: 'openid insight:read insight:write dashboard:write',
                    required_scopes: 'insight:write dashboard:write',
                },
            },
        ])
        expect(readJson(result.files[ADD_PENDING_FILE] ?? '{}')).toMatchObject({
            deviceCode: DEVICE_CODE,
            projectId: '42',
        })
    })

    test.each([
        ['in the same project, the login keeps its id', OAUTH_LOGIN, 'login-1', REFRESH_TOKEN],
        [
            'over a personal API key, the login gets a new id',
            KEYCHAIN_LOGIN,
            expect.not.stringMatching(/^phx_/),
            undefined,
        ],
    ])('add --wait replaces the stored login: %s', async (_name, stored, loginId, revoked) => {
        const scopes = ['openid', 'insight:read', 'insight:write']
        const result = await runHog(['auth', 'add', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: {
                ...stored.files,
                [ADD_PENDING_FILE]: JSON.stringify({
                    ...(readJson(PENDING) as object),
                    scopes,
                    requiredScopes: ['insight:write'],
                }),
            },
            keychain: stored.keychain,
            respond: deviceFlow(0, {
                status: 200,
                body: {
                    ...APPROVED,
                    access_token: STEPPED_UP_ACCESS,
                    refresh_token: STEPPED_UP_REFRESH,
                    scope: scopes.join(' '),
                },
            }),
        })

        expect(result.json()).toMatchObject({ status: 'added', projectId: '42', scopes })
        expect(readJson(result.keychain[EU_ITEM] ?? '{}')).toEqual({
            accessToken: STEPPED_UP_ACCESS,
            refreshToken: STEPPED_UP_REFRESH,
        })
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toMatchObject({
            logins: { [EU]: { '42': { loginId, scopes } } },
        })
        const revoke = result.requests.find((request) => request.url.endsWith('/oauth/revoke/'))
        expect((revoke?.body as { token?: string } | undefined)?.token).toBe(revoked)
        expect(result.files[ADD_PENDING_FILE]).toBeUndefined()
    })

    test.each([
        [
            'PostHog drops a required scope',
            { scope: 'openid insight:read' },
            {
                code: 'scopes_not_granted',
                hint: expect.stringContaining(`\`hog auth add --host ${EU} insight:write\``),
            },
        ],
        [
            'the person approves another project than the one that asked',
            { scope: 'openid insight:read insight:write', scoped_teams: [7] },
            { code: 'step_up_other_project', hint: expect.stringContaining('pick project 42') },
        ],
    ])('add --wait keeps the current login when %s', async (_name, approved, expected) => {
        const result = await runHog(['auth', 'add', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: {
                ...OAUTH_LOGIN.files,
                [ADD_PENDING_FILE]: JSON.stringify({
                    ...(readJson(PENDING) as object),
                    scopes: ['openid', 'insight:read', 'insight:write'],
                    requiredScopes: ['insight:write'],
                    projectId: '42',
                }),
            },
            keychain: OAUTH_LOGIN.keychain,
            respond: deviceFlow(0, {
                status: 200,
                body: {
                    ...APPROVED,
                    access_token: STEPPED_UP_ACCESS,
                    refresh_token: STEPPED_UP_REFRESH,
                    ...approved,
                },
            }),
        })

        expect(result.error()).toMatchObject(expected)
        expect(result.keychain).toEqual(OAUTH_LOGIN.keychain)
        const revoke = result.requests.find((request) => request.url.endsWith('/oauth/revoke/'))
        expect((revoke?.body as { token?: string } | undefined)?.token).toBe(STEPPED_UP_REFRESH)
        expect(result.files[ADD_PENDING_FILE]).toBeUndefined()
    })

    test('add --wait saves the scopes for the project that asked for them, not the one the folder uses', async () => {
        const scopes = ['openid', 'insight:read', 'insight:write']
        const result = await runHog(['auth', 'add', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: settingsJson(
                    EU,
                    { ...OAUTH_RECORD, projectId: '7', loginId: 'login-7', loggedInAt: 1 },
                    { ...OAUTH_RECORD, loggedInAt: 2 }
                ),
                [ADD_PENDING_FILE]: JSON.stringify({
                    ...(readJson(PENDING) as object),
                    scopes,
                    requiredScopes: ['insight:write'],
                    projectId: '7',
                }),
            },
            keychain: { ...OAUTH_LOGIN.keychain, [`${EU}#7`]: OAUTH_LOGIN.keychain[EU_ITEM] },
            respond: deviceFlow(0, {
                status: 200,
                body: {
                    ...APPROVED,
                    access_token: STEPPED_UP_ACCESS,
                    refresh_token: STEPPED_UP_REFRESH,
                    scope: scopes.join(' '),
                    scoped_teams: [7],
                },
            }),
        })

        expect(result.json()).toMatchObject({ status: 'added', projectId: '7', scopes })
        expect(readJson(result.keychain[`${EU}#7`] ?? '{}')).toMatchObject({ accessToken: STEPPED_UP_ACCESS })
        expect(result.keychain[EU_ITEM]).toBe(OAUTH_LOGIN.keychain[EU_ITEM])
    })

    test.each([
        ['rejected', 'access_denied', 'login_rejected'],
        ['expired', 'expired_token', 'login_expired'],
    ])('add --wait %s tells an agent the command that asks for the same scopes again', async (_name, error, code) => {
        const result = await runHog(['auth', 'add', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: {
                ...OAUTH_LOGIN.files,
                [ADD_PENDING_FILE]: JSON.stringify({
                    ...(readJson(PENDING) as object),
                    scopes: ['openid', 'insight:read', 'insight:write', 'dashboard:write'],
                    requiredScopes: ['insight:write', 'dashboard:write'],
                }),
            },
            keychain: OAUTH_LOGIN.keychain,
            respond: deviceFlow(0, { status: 400, body: { error } }),
        })

        expect(result.error()).toMatchObject({
            code,
            hint: expect.stringContaining(`\`hog auth add --host ${EU} insight:write dashboard:write\``),
        })
        expect(result.keychain[EU_ITEM]).toBe(OAUTH_LOGIN.keychain[EU_ITEM])
        expect(result.files[ADD_PENDING_FILE]).toBeUndefined()
    })

    test.each([
        [
            'an object without an access level',
            ['insight'],
            {},
            { code: 'unknown_scope', hint: expect.stringContaining('insight:write') },
        ],
        ['a scope PostHog does not have', ['insight:admin'], {}, { code: 'unknown_scope' }],
        [
            'a scope this hog does not know',
            ['newthing:read'],
            {},
            { code: 'unknown_scope', hint: expect.stringContaining('update hog') },
        ],
        [
            'a personal API key',
            ['insight:write'],
            { HOG_PERSONAL_API_KEY: 'phx_secret', HOG_PROJECT_ID: '42' },
            { code: 'step_up_unavailable', hint: expect.stringContaining('insight:write') },
        ],
    ])('add refuses %s without asking PostHog', async (_name, scopes, env, expected) => {
        const result = await runHog(['auth', 'add', ...scopes], {
            env: { CLAUDECODE: '1', ...env },
            ...OAUTH_LOGIN,
            respond: deviceFlow(0),
        })

        expect(result.error()).toMatchObject(expected)
        expect(result.requests).toEqual([])
    })

    test('add skips the browser when write access already covers the scope', async () => {
        const result = await runHog(['auth', 'add', 'insight:read'], {
            env: { CLAUDECODE: '1' },
            files: {
                ...OAUTH_LOGIN.files,
                [SETTINGS_FILE]: OAUTH_LOGIN.files[SETTINGS_FILE].replace('"insight:read"', '"insight:write"'),
            },
            keychain: OAUTH_LOGIN.keychain,
            respond: deviceFlow(0),
        })

        expect(result.json()).toMatchObject({ status: 'already_granted' })
        expect(result.requests).toEqual([])
    })

    const CHALLENGE = 'Bearer error="insufficient_scope", scope="insight:read query:read dashboard:write"'

    const flow = deviceFlow(0, {
        status: 200,
        body: {
            ...APPROVED,
            access_token: STEPPED_UP_ACCESS,
            refresh_token: STEPPED_UP_REFRESH,
            scope: 'openid insight:read query:read dashboard:write',
        },
    })
    const challengedQuery = (
        url: string,
        _body: unknown,
        authorization: string | null
    ): { status: number; body: unknown; headers?: Record<string, string> } =>
        !url.endsWith('/query')
            ? flow(url)
            : authorization === `Bearer ${STEPPED_UP_ACCESS}`
              ? { status: 200, body: ROWS }
              : { status: 403, body: { detail: 'missing scope' }, headers: { 'WWW-Authenticate': CHALLENGE } }

    test('an agent at a terminal gets the step-up command for the scopes a request lacks, without a prompt', async () => {
        const result = await runHog(['query', 'run', 'select 1'], {
            env: { CLAUDECODE: '1' },
            stdoutIsTTY: true,
            ...OAUTH_LOGIN,
            respond: challengedQuery,
        })

        expect(result.error()).toMatchObject({
            code: 'step_up_required',
            scopes: ['query:read', 'dashboard:write'],
            command: `hog auth add --host ${EU} query:read dashboard:write`,
            hint: expect.stringContaining(`hog auth add --host ${EU} query:read dashboard:write`),
        })
        expect(result.requests.map((request) => request.url)).toEqual([`${EU}/api/environments/42/query`])
    })

    test('at a terminal, a yes adds the scopes and sends the request again with the new token', async () => {
        const result = await runHog(['query', 'run', 'select 1'], {
            stdoutIsTTY: true,
            answers: ['yes'],
            ...OAUTH_LOGIN,
            respond: challengedQuery,
        })

        expect(result.exitCode).toBe(0)
        expect(result.requests.find((request) => request.url.endsWith('/device-authorization/'))?.body).toEqual({
            client_id: HOG_CLIENT_ID,
            scope: 'openid insight:read query:read dashboard:write',
            required_scopes: 'query:read dashboard:write',
        })
        expect(result.requests.filter((request) => request.url.endsWith('/query'))).toHaveLength(2)
        expect(readJson(result.files[SETTINGS_FILE] ?? '{}')).toMatchObject({
            logins: { [EU]: { '42': { loginId: 'login-1' } } },
        })
    })

    test('status treats a challenged 403 as a missing detail and asks nothing', async () => {
        const result = await runHog(['auth', 'status'], {
            stdoutIsTTY: true,
            ...OAUTH_LOGIN,
            respond: (url) =>
                url.endsWith('/api/users/@me/')
                    ? { status: 403, body: { detail: 'missing scope' }, headers: { 'WWW-Authenticate': CHALLENGE } }
                    : { status: 200, body: { name: 'Hedgebox' } },
        })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain('Hedgebox')
    })

    test.each([
        ['an endpoint', 'name: daily\nquery: SELECT 1\n', 'endpoint:write'],
        [
            'an endpoint with a variable PostHog lacks',
            'name: daily\nquery: SELECT {variables.day}\nvariables:\n  - name: day\n    type: String\n',
            'endpoint:write insight_variable:write',
        ],
    ])('push checks the login can create %s before it writes anything', async (_name, yaml, scopes) => {
        const result = await runHog(['endpoints', 'push', 'daily.yaml', '--yes'], {
            env: { CLAUDECODE: '1' },
            files: { ...OAUTH_LOGIN.files, '/work/daily.yaml': yaml },
            keychain: OAUTH_LOGIN.keychain,
            respond: (url) =>
                /\/(endpoints|insight_variables)\/(\?.*)?$/.test(url)
                    ? { status: 200, body: { results: [] } }
                    : { status: 404, body: { detail: 'Not found.' } },
        })

        expect(result.error()).toMatchObject({
            code: 'step_up_required',
            command: `hog auth add --host ${EU} ${scopes}`,
        })
        expect(result.requests.filter((request) => request.method !== 'GET')).toEqual([])
    })

    test('push stops when the approved step-up drops a scope the login already had', async () => {
        const flow = deviceFlow(0, {
            status: 200,
            body: {
                ...APPROVED,
                access_token: STEPPED_UP_ACCESS,
                refresh_token: STEPPED_UP_REFRESH,
                scope: 'openid insight_variable:write',
            },
        })
        const result = await runHog(['endpoints', 'push', 'daily.yaml', '--yes'], {
            stdoutIsTTY: true,
            answers: ['yes'],
            files: {
                ...OAUTH_LOGIN.files,
                [SETTINGS_FILE]: OAUTH_LOGIN.files[SETTINGS_FILE].replace('"insight:read"', '"endpoint:write"'),
                '/work/daily.yaml':
                    'name: daily\nquery: SELECT {variables.day}\nvariables:\n  - name: day\n    type: String\n',
            },
            keychain: OAUTH_LOGIN.keychain,
            respond: (url) =>
                /\/(endpoints|insight_variables)\/(\?.*)?$/.test(url)
                    ? { status: 200, body: { results: [] } }
                    : flow(url),
        })

        expect(result.exitCode).toBe(1)
        expect(
            result.requests.filter((request) => request.method === 'POST' && !request.url.includes('/oauth/'))
        ).toEqual([])
    })
})
