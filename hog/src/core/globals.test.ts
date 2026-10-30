import { describe, expect, test } from 'bun:test'

import { runHog, TEST_CREDENTIALS } from '@/testing'

const AGENT = { CLAUDECODE: '1' }
const ENDPOINTS = 'https://ph.example.com/api/environments/7/endpoints/'

const threePages = (url: string): { status: number; body: unknown } => {
    const page = Number(new URL(url).searchParams.get('page') ?? '1')
    return { status: 200, body: { results: [], next: page < 3 ? `${ENDPOINTS}?page=${page + 1}&token=secret` : null } }
}

describe('global options', () => {
    test.each([
        ['--no-fail', ['--no-fail'], {}, {}],
        ['HOG_NO_FAIL', [], { HOG_NO_FAIL: '1' }, {}],
        ['cli.noFail in posthog.json', [], {}, { '/work/posthog.json': JSON.stringify({ cli: { noFail: true } }) }],
    ])('%s turns a failure into exit code 0 and still prints it', async (_name, flags, env, files) => {
        const result = await runHog(['endpoints', 'list', ...flags], { env: { ...AGENT, ...env }, files })
        expect(result.exitCode).toBe(0)
        expect(result.error().code).toBe('not_authenticated')
    })

    test('--no-fail covers a result that reports a problem', async () => {
        const result = await runHog(['endpoints', 'diff', 'a.yaml', '--no-fail'], {
            env: { ...AGENT, ...TEST_CREDENTIALS },
            files: { '/work/a.yaml': 'name: a\nquery: SELECT 1\n' },
            respond: () => ({ status: 200, body: { results: [] } }),
        })
        expect(result.json().plan).toEqual([expect.objectContaining({ action: 'create' })])
        expect(result.exitCode).toBe(0)
    })

    test('--no-fail keeps usage errors at exit code 2', async () => {
        const result = await runHog(['endpoints', 'run', '--no-fail'], { env: { ...AGENT, ...TEST_CREDENTIALS } })
        expect(result.exitCode).toBe(2)
    })

    test.each([
        ['an env var', { HOG_RATE_LIMIT: '2' }, {}],
        ['posthog.json', {}, { '/work/posthog.json': JSON.stringify({ cli: { rateLimit: 2 } }) }],
    ])('a rate limit from %s holds the third request in a minute', async (_name, env, files) => {
        const result = await runHog(['endpoints', 'list'], {
            env: { ...AGENT, ...TEST_CREDENTIALS, ...env },
            files,
            respond: threePages,
        })
        expect(result.requests).toHaveLength(3)
        expect(result.elapsedMs).toBe(60_000)
    })

    test('a flag beats the env var, which beats posthog.json', async () => {
        const result = await runHog(['endpoints', 'list', '--rate-limit', '100'], {
            env: { ...AGENT, ...TEST_CREDENTIALS, HOG_RATE_LIMIT: '1' },
            files: { '/work/posthog.json': JSON.stringify({ cli: { rateLimit: 1 } }) },
            respond: threePages,
        })
        expect(result.elapsedMs).toBe(0)
    })

    test('a rate limit leaves signed storage URLs alone, as posthog-cli does', async () => {
        const result = await runHog(['et', 'download', '0192f0a0-0000-7000-8000-000000000001', '--rate-limit', '1'], {
            env: { ...AGENT, ...TEST_CREDENTIALS },
            respond: (url) =>
                url.endsWith('/download/')
                    ? { status: 200, body: { url: 'https://storage.example.com/symbol-set' } }
                    : { status: 500, body: {} },
        })

        expect(result.requests.map((request) => new URL(request.url).host)).toEqual([
            'ph.example.com',
            'storage.example.com',
        ])
        expect(result.elapsedMs).toBe(0)
    })

    test('HOG_DEBUG prints each request without its query string', async () => {
        const result = await runHog(['endpoints', 'list'], {
            env: { ...AGENT, ...TEST_CREDENTIALS, HOG_DEBUG: 'true' },
            respond: threePages,
        })
        expect(result.stderr).toContain(`[debug] GET ${ENDPOINTS} 200`)
        expect(result.stderr).not.toContain('secret')
    })

    test.each([
        ['an env flag that is not a boolean', ['endpoints', 'list'], { HOG_DEBUG: 'maybe' }],
        ['a rate limit that is not a number', ['endpoints', 'list'], { HOG_RATE_LIMIT: 'fast' }],
    ])('%s is a usage error', async (_name, argv, env) => {
        const result = await runHog(argv, { env: { ...AGENT, ...TEST_CREDENTIALS, ...env } })
        expect(result.exitCode).toBe(2)
        expect(result.error().code).toBe('invalid_setting')
    })

    test('HOG_OUTPUT picks the format', async () => {
        const result = await runHog(['commands'], { env: { HOG_OUTPUT: 'json' }, stdoutIsTTY: true })
        expect(() => JSON.parse(result.stdout)).not.toThrow()
    })

    test('--skip-ssl-verification turns off certificate checks', async () => {
        const result = await runHog(['commands', '--skip-ssl-verification'], { env: AGENT })
        expect(result.tls.verify).toBe(false)
    })

    test('HOG_DRY_RUN dry-runs every command that writes, and fails the ones that cannot', async () => {
        const env = { ...AGENT, ...TEST_CREDENTIALS, HOG_DRY_RUN: '1' }
        const push = await runHog(['endpoints', 'push', 'a.yaml'], {
            env,
            files: { '/work/a.yaml': 'name: a\nquery: SELECT 1\n' },
            respond: () => ({ status: 200, body: { results: [] } }),
        })
        expect(push.json()).toMatchObject({ status: 'preview' })

        const pull = await runHog(['schema', 'pull', '-l', 'python'], {
            env,
            respond: () => ({ status: 200, body: { content: 'x = 1\n', event_count: 1, schema_hash: 'h' } }),
        })
        expect(pull.json()).toMatchObject({ status: 'would_write' })
        expect(pull.files).toEqual({})

        const logout = await runHog(['auth', 'logout'], {
            env,
            files: { '/home/test/.posthog/credentials.json': '{}' },
        })
        expect(logout.exitCode).toBe(2)
        expect(logout.error().code).toBe('dry_run_unsupported')
        expect(logout.files).toEqual({ '/home/test/.posthog/credentials.json': '{}' })
    })

    test.each([
        [
            'a posthog.json host that matches the credentials',
            'https://stored.example.com',
            {},
            'https://stored.example.com',
        ],
        [
            'HOG_HOST beats posthog.json',
            'https://config.example.com',
            { HOG_HOST: 'https://env.example.com' },
            'https://env.example.com',
        ],
    ])('%s', async (_name, configHost, env, host) => {
        const result = await runHog(['endpoints', 'list'], {
            env: { ...AGENT, ...env },
            files: {
                '/work/posthog.json': JSON.stringify({ host: configHost }),
                '/home/test/.posthog/credentials.json': JSON.stringify({
                    token: 'phx_test',
                    env_id: '7',
                    host: 'https://stored.example.com',
                }),
            },
            respond: () => ({ status: 200, body: { results: [] } }),
        })

        expect(result.requests[0]!.url).toStartWith(`${host}/api/`)
    })

    test('a posthog.json host never receives credentials stored for another host', async () => {
        const result = await runHog(['endpoints', 'list'], {
            env: AGENT,
            files: {
                '/work/posthog.json': JSON.stringify({ host: 'https://config.example.com' }),
                '/home/test/.posthog/credentials.json': JSON.stringify({
                    token: 'phx_test',
                    env_id: '7',
                    host: 'https://stored.example.com',
                }),
            },
        })

        expect(result.error().code).toBe('host_mismatch')
        expect(result.requests).toEqual([])
    })

    test('a posthog.json hog cannot read stops the command before it sends anything', async () => {
        const result = await runHog(['endpoints', 'list'], {
            env: { ...AGENT, ...TEST_CREDENTIALS },
            files: { '/work/posthog.json': '{ "cli": ' },
        })
        expect(result.error().code).toBe('invalid_config')
        expect(result.requests).toEqual([])
    })
})
