import { describe, expect, test } from 'bun:test'

import type { Secrets } from '@/core/runtime'
import { runHog } from '@/testing'

const LEGACY_CLI_FILE = '/home/test/.posthog/credentials.json'
const SETTINGS_FILE = '/home/test/.config/hog/settings.json'
const HOG_CREDENTIALS_FILE = '/home/test/.config/hog/credentials.json'
const PENDING_FILE = '/home/test/.config/hog/pending-auth-login.json'
const DEVICE_CODE = 'device-secret-123'

const DEVICE = {
    device_code: DEVICE_CODE,
    user_code: 'ABCD-1234',
    verification_uri_complete: 'https://eu.posthog.com/cli/authorize?code=ABCD-1234',
    expires_in: 600,
    interval: 5,
}
const APPROVED = {
    status: 'authorized',
    personal_api_key: 'phx_secret',
    project_id: '42',
    scopes: ['query:read'],
}
const PENDING = JSON.stringify({
    host: 'https://eu.posthog.com',
    deviceCode: DEVICE_CODE,
    userCode: 'ABCD-1234',
    url: 'https://eu.posthog.com/cli/authorize?code=ABCD-1234&use_cases=agent-cli',
    expiresAt: Date.UTC(2026, 0, 1) + 600_000,
    intervalSeconds: 5,
})

// The device flow: a device code, then `pendingPolls` answers of "keep waiting", then `final`.
function deviceFlow(pendingPolls: number, final = { status: 200, body: APPROVED as unknown }) {
    let polls = 0
    return (url: string) => {
        if (url.endsWith('/api/cli-auth/device-code/')) {
            return { status: 200, body: DEVICE }
        }
        return polls++ < pendingPolls ? { status: 202, body: { status: 'pending' } } : final
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
            code: 'ABCD-1234',
            url: 'https://eu.posthog.com/cli/authorize?code=ABCD-1234&use_cases=agent-cli',
            next: 'hog auth login --wait',
        })
        expect(result.stdout).not.toContain(DEVICE_CODE)
        expect(JSON.parse(result.files[PENDING_FILE] ?? '{}')).toMatchObject({ deviceCode: DEVICE_CODE })
        expect(result.opened).toEqual([])
        expect(result.requests.map((request) => request.url)).toEqual([
            'https://eu.posthog.com/api/cli-auth/device-code/',
        ])
    })

    test.each([
        ['a posthog.json Cloud host picks the region', [], 'https://eu.posthog.com', 'https://eu.posthog.com'],
        [
            '--region beats the posthog.json host',
            ['--region', 'eu'],
            'https://us.posthog.com',
            'https://eu.posthog.com',
        ],
    ])('%s', async (_name, flags, configHost, loginHost) => {
        const result = await runHog(['auth', 'login', ...flags], {
            env: { CLAUDECODE: '1' },
            files: { '/work/posthog.json': JSON.stringify({ host: configHost }) },
            respond: deviceFlow(0),
        })

        expect(result.exitCode).toBe(0)
        expect(result.requests.map((request) => request.url)).toEqual([`${loginHost}/api/cli-auth/device-code/`])
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
        expect(result.json()).toMatchObject({ status: 'pending', code: 'ABCD-1234' })
        expect(result.requests).toEqual([])
    })

    test.each([
        ['an agent without a region', ['auth', 'login'], { CLAUDECODE: '1' }, {}, 2, 'region_required'],
        ['a CI job', ['auth', 'login', '--region', 'us'], { CI: 'true' }, {}, 1, 'login_needs_a_person'],
        ['--wait with no login started', ['auth', 'login', '--wait'], { CLAUDECODE: '1' }, {}, 1, 'no_pending_login'],
    ])('%s fails with a hint', async (_name, argv, env, files, exitCode, code) => {
        const result = await runHog(argv, { env, files, respond: deviceFlow(0) })
        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })

    test('--wait saves the key in the keychain once the person approves', async () => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(2),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ status: 'logged_in', host: 'https://eu.posthog.com', projectId: '42' })
        expect(result.stdout).not.toContain('phx_secret')
        // The keychain keeps only the secret. What isn't secret is in settings.json.
        expect(JSON.parse(result.keychain['https://eu.posthog.com'] ?? '{}')).toEqual({ apiKey: 'phx_secret' })
        expect(JSON.parse(result.files[SETTINGS_FILE] ?? '{}')).toEqual({
            logins: {
                'https://eu.posthog.com': {
                    store: 'keychain',
                    type: 'personal_api_key',
                    projectId: '42',
                    host: 'https://eu.posthog.com',
                },
            },
            host: 'https://eu.posthog.com',
        })
        expect(result.files[LEGACY_CLI_FILE]).toBeUndefined()
        expect(result.files[PENDING_FILE]).toBeUndefined()
        // Only polls: a key PostHog just issued skips the key check.
        expect(result.requests.map((request) => request.url.endsWith('/poll/'))).toEqual([true, true, true])
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
        'a login saves the key in a private file, and says so, when the keychain %s',
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
            expect(JSON.parse(result.files[HOG_CREDENTIALS_FILE] ?? '{}')).toEqual({
                'https://eu.posthog.com': { apiKey: 'phx_secret' },
            })
            expect(JSON.parse(result.files[SETTINGS_FILE] ?? '{}')).toMatchObject({
                logins: { 'https://eu.posthog.com': { store: 'file', projectId: '42' } },
            })
        }
    )

    test.each([
        [
            'stops when the code expires and forgets it',
            { status: 400, body: { status: 'expired' } },
            'login_expired',
            false,
        ],
        [
            'retries a server that keeps failing, then keeps the login to resume',
            { status: 503, body: 'Service Unavailable' },
            'login_interrupted',
            true,
        ],
    ])('--wait %s', async (_name, final, code, keepsPending) => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(1, final),
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code })
        expect(result.files[PENDING_FILE] !== undefined).toBe(keepsPending)
        expect(result.keychain).toEqual({})
    })

    test.each([
        ['approving in the browser', ['eu'], true, 'https://eu.posthog.com'],
        [
            'pasting a personal API key',
            ['key', 'https://ph.example.com/', '42', 'phx_secret'],
            false,
            'https://ph.example.com',
        ],
    ])('a person at a terminal logs in by %s', async (_name, answers, opensBrowser, host) => {
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
        expect(JSON.parse(result.keychain[host] ?? '{}')).toEqual({ apiKey: 'phx_secret' })
    })

    const STORED = JSON.stringify({ host: 'https://eu.posthog.com', token: 'phx_secret', env_id: '42' })
    const KEYCHAIN_LOGIN = {
        files: {
            [SETTINGS_FILE]: JSON.stringify({
                logins: {
                    'https://eu.posthog.com': {
                        store: 'keychain',
                        type: 'personal_api_key',
                        projectId: '42',
                        host: 'https://eu.posthog.com',
                    },
                },
                host: 'https://eu.posthog.com',
            }),
        },
        keychain: { 'https://eu.posthog.com': JSON.stringify({ apiKey: 'phx_secret' }) },
    }

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

    test.each([['a hog login', KEYCHAIN_LOGIN, { source: 'store', store: 'keychain', credentialsPath: null }]])(
        'status names where the key of %s comes from',
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
        expect(result.json()).toEqual({ authenticated: false, next: 'hog auth login' })
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
                [SETTINGS_FILE]: JSON.stringify({
                    logins: {
                        'https://eu.posthog.com': {
                            store: 'file',
                            type: 'personal_api_key',
                            projectId: '42',
                            host: 'https://eu.posthog.com',
                            keychainLeftover: true,
                        },
                    },
                    host: 'https://eu.posthog.com',
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
                [SETTINGS_FILE]: JSON.stringify({
                    logins: {
                        'https://eu.posthog.com': {
                            store: 'keychain',
                            type: 'personal_api_key',
                            projectId: '42',
                            host: 'https://eu.posthog.com',
                        },
                        'https://us.posthog.com': {
                            store: 'keychain',
                            type: 'personal_api_key',
                            projectId: '42',
                            host: 'https://us.posthog.com',
                        },
                    },
                    host: 'https://us.posthog.com',
                }),
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
            expect(result.exitCode).toBe(0)
            expect(result.json()).toMatchObject({ status, revokeUrl, stillSet })
            expect(result.keychain).toEqual(files[SETTINGS_FILE] ? {} : KEYCHAIN_LOGIN.keychain)
            expect(result.files[PENDING_FILE]).toBeUndefined()
            expect(result.files[LEGACY_CLI_FILE]).toBe(files[LEGACY_CLI_FILE])
        }
    )

    test('a file login that replaced a keychain login takes the old keychain item with it on logout', async () => {
        const oldItem = JSON.stringify({ apiKey: 'phx_old' })
        const items = new Map([['https://eu.posthog.com', oldItem]])
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
        const login = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { ...KEYCHAIN_LOGIN.files, [PENDING_FILE]: PENDING },
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
        expect(items.get('https://eu.posthog.com')).toBe(oldItem)

        keychainWorks.now = true
        const removed = await runHog(['auth', 'logout'], {
            env: { CLAUDECODE: '1' },
            files: login.files,
            secrets: () => secrets,
        })
        expect(removed.json()).toMatchObject({ status: 'logged_out', keychainLeftover: null })
        expect(items.size).toBe(0)
    })

    test('logout --all removes every login, and the leftovers settings.json no longer names', async () => {
        const record = (host: string, store: string): Record<string, string> => ({
            store,
            type: 'personal_api_key',
            projectId: '42',
            host,
        })
        const result = await runHog(['auth', 'logout', '--all'], {
            env: { CLAUDECODE: '1' },
            files: {
                [SETTINGS_FILE]: JSON.stringify({
                    logins: {
                        'https://eu.posthog.com': record('https://eu.posthog.com', 'keychain'),
                        'https://us.posthog.com': {
                            ...record('https://us.posthog.com', 'file'),
                            keychainLeftover: true,
                        },
                    },
                    host: 'https://us.posthog.com',
                }),
                [HOG_CREDENTIALS_FILE]: JSON.stringify({
                    'https://us.posthog.com': { apiKey: 'phx_us' },
                    'https://posthog.example.com': { apiKey: 'phx_orphan' },
                }),
                [PENDING_FILE]: PENDING,
            },
            keychain: {
                ...KEYCHAIN_LOGIN.keychain,
                'https://us.posthog.com': JSON.stringify({ apiKey: 'phx_before_fallback' }),
                'https://posthog.example.com': JSON.stringify({ apiKey: 'phx_before_settings_were_lost' }),
            },
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            status: 'logged_out',
            hosts: [
                { host: 'https://eu.posthog.com', revokeUrl: 'https://eu.posthog.com/settings/user-api-keys' },
                { host: 'https://us.posthog.com', revokeUrl: 'https://us.posthog.com/settings/user-api-keys' },
                { host: 'https://posthog.example.com', revokeUrl: null },
            ],
        })
        expect(result.keychain).toEqual({})
        expect(result.files[HOG_CREDENTIALS_FILE]).toBeUndefined()
        expect(JSON.parse(result.files[SETTINGS_FILE] ?? '{}')).toEqual({ logins: {} })
        expect(result.files[PENDING_FILE]).toBeUndefined()
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
})
