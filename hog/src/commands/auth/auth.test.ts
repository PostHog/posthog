import { describe, expect, test } from 'bun:test'

import { runHog } from '@/testing'

const CREDENTIALS_FILE = '/home/test/.posthog/credentials.json'
const PENDING_FILE = '/home/test/.posthog/login-pending.json'
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

    test('--wait saves the key in the file posthog-cli reads once the person approves', async () => {
        const result = await runHog(['auth', 'login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(2),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ status: 'logged_in', host: 'https://eu.posthog.com', projectId: '42' })
        expect(result.stdout).not.toContain('phx_secret')
        expect(JSON.parse(result.files[CREDENTIALS_FILE] ?? '{}')).toEqual({
            host: 'https://eu.posthog.com',
            token: 'phx_secret',
            env_id: '42',
        })
        expect(result.files[PENDING_FILE]).toBeUndefined()
        expect(result.requests.filter((request) => request.url.endsWith('/poll/'))).toHaveLength(3)
    })

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
        expect(result.files[CREDENTIALS_FILE]).toBeUndefined()
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
        expect(JSON.parse(result.files[CREDENTIALS_FILE] ?? '{}')).toMatchObject({
            host,
            token: 'phx_secret',
            env_id: '42',
        })
    })

    const STORED = JSON.stringify({ host: 'https://eu.posthog.com', token: 'phx_secret', env_id: '42' })

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
            files: { [CREDENTIALS_FILE]: STORED },
            respond: (url) =>
                url.endsWith('/api/users/@me/')
                    ? { status: userStatus, body: { email: 'ana@example.com' } }
                    : { status: projectStatus, body: { name: 'Shop' } },
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.json()).toMatchObject({ host: 'https://eu.posthog.com', projectId: '42', ...expected })
        expect(result.stdout).not.toContain('phx_secret')
    })

    test('status escapes terminal control characters in the project name', async () => {
        const result = await runHog(['auth', 'status'], {
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
            files: { [CREDENTIALS_FILE]: STORED },
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
            files: { [CREDENTIALS_FILE]: STORED },
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
            { [CREDENTIALS_FILE]: STORED, [PENDING_FILE]: PENDING },
            {},
            'logged_out',
            'https://eu.posthog.com/settings/user-api-keys',
            [],
        ],
        ['no stored key', {}, {}, 'not_logged_in', null, []],
        [
            'a key in the environment',
            { [CREDENTIALS_FILE]: STORED },
            { HOG_API_KEY: 'phx_env' },
            'logged_out',
            'https://eu.posthog.com/settings/user-api-keys',
            ['HOG_API_KEY'],
        ],
    ])('logout with %s removes what hog stored', async (_name, files, env, status, revokeUrl, stillSet) => {
        const result = await runHog(['auth', 'logout'], { env: { CLAUDECODE: '1', ...env }, files })
        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ status, revokeUrl, stillSet })
        expect(result.files[CREDENTIALS_FILE]).toBeUndefined()
        expect(result.files[PENDING_FILE]).toBeUndefined()
    })
})
