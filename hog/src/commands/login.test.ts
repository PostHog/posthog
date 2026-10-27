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

describe('hog login', () => {
    test('an agent gets a link to hand over, without blocking or seeing the device code', async () => {
        const result = await runHog(['login', '--region', 'eu'], { env: { CLAUDECODE: '1' }, respond: deviceFlow(0) })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            status: 'pending',
            code: 'ABCD-1234',
            url: 'https://eu.posthog.com/cli/authorize?code=ABCD-1234&use_cases=agent-cli',
            next: 'hog login --wait',
        })
        expect(result.stdout).not.toContain(DEVICE_CODE)
        expect(JSON.parse(result.files[PENDING_FILE] ?? '{}')).toMatchObject({ deviceCode: DEVICE_CODE })
        expect(result.opened).toEqual([])
        expect(result.requests.map((request) => request.url)).toEqual([
            'https://eu.posthog.com/api/cli-auth/device-code/',
        ])
    })

    test('an agent that retries gets the same code, so the link it shared keeps working', async () => {
        const result = await runHog(['login', '--region', 'eu'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(0),
        })
        expect(result.json()).toMatchObject({ status: 'pending', code: 'ABCD-1234' })
        expect(result.requests).toEqual([])
    })

    test.each([
        ['an agent without a region', ['login'], { CLAUDECODE: '1' }, {}, 2, 'region_required'],
        ['a CI job', ['login', '--region', 'us'], { CI: 'true' }, {}, 1, 'login_needs_a_person'],
        ['--wait with no login started', ['login', '--wait'], { CLAUDECODE: '1' }, {}, 1, 'no_pending_login'],
    ])('%s fails with a hint', async (_name, argv, env, files, exitCode, code) => {
        const result = await runHog(argv, { env, files, respond: deviceFlow(0) })
        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })

    test('--wait saves the key in the file posthog-cli reads once the person approves', async () => {
        const result = await runHog(['login', '--wait'], {
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

    test('--wait stops when the code expires and forgets it', async () => {
        const result = await runHog(['login', '--wait'], {
            env: { CLAUDECODE: '1' },
            files: { [PENDING_FILE]: PENDING },
            respond: deviceFlow(1, { status: 400, body: { status: 'expired' } }),
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'login_expired' })
        expect(result.files[PENDING_FILE]).toBeUndefined()
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
        const result = await runHog(['login'], {
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
            answers,
            respond: deviceFlow(1),
        })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain(`Logged in to ${host}, project 42.`)
        expect(result.opened).toHaveLength(opensBrowser ? 1 : 0)
        expect(JSON.parse(result.files[CREDENTIALS_FILE] ?? '{}')).toMatchObject({
            host,
            token: 'phx_secret',
            env_id: '42',
        })
    })
})
