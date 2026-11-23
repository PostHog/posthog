import { describe, expect, test } from 'bun:test'
import { z } from 'zod'

import { EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import { runHog, TEST_CREDENTIALS, type FakeRuntimeOptions, type HogRun } from '@/testing'

const api = 'https://ph.example.com/api/projects/7/stacks/web/secrets/'
const name = 'WAREHOUSE_KEY'
const secret = 'private-test-value'
const updated_at = '2026-11-21T12:00:00Z'
const base: FakeRuntimeOptions = {
    env: TEST_CREDENTIALS,
    files: { '/work/posthog.json': '{"stacks":{"web":{"dir":".ph"}}}' },
    telemetryToken: 'phc_test',
}
const path = ['stack', 'secret']

function expectPrivate(result: HogRun): void {
    const usage = result.requests.filter(({ url }) => url.endsWith('/batch/'))
    expect(usage.length).toBeGreaterThan(0)
    expect(JSON.stringify([result.stdout, result.stderr, result.promptMessages, usage])).not.toContain(secret)
}

describe('stack secrets', () => {
    test.each([
        { flags: [], tty: true, explicitStdin: false },
        { flags: ['-o', 'json'], tty: false, explicitStdin: false },
        { flags: ['--raw', '--debug'], tty: false, explicitStdin: true },
    ])(
        'set reads private input and outputs only the name ($flags, tty=$tty)',
        async ({ flags, tty, explicitStdin }) => {
            const value = tty ? secret : ` ${secret}\nsecond line\n`
            const result = await runHog([...path, 'set', name, ...(explicitStdin ? ['-'] : []), ...flags], {
                ...base,
                stdoutIsTTY: tty,
                answers: tty ? [value] : [],
                stdin: tty ? '' : value,
                respond: (url) =>
                    url.startsWith(api)
                        ? { status: 200, body: { name, updated_at, value } }
                        : { status: 200, body: {} },
            })
            expect(result.exitCode).toBe(EXIT_SUCCESS)
            expect(result.requests.filter(({ url }) => url.startsWith(api))).toEqual([
                { method: 'PUT', url: `${api}${name}/`, body: { value } },
            ])
            if (tty) {
                expect(result.stdout).toContain(`Set secret ${name}`)
                expect(result.stdout).not.toContain('line break')
                expect(result.promptMessages).toContain(`Value for ${name}`)
            } else {
                expect(result.json()).toEqual({
                    name,
                    endsWithLineBreak: true,
                    note: expect.stringContaining("printf '%s'"),
                })
            }
            expectPrivate(result)
        }
    )

    test.each([secret, `--${secret}`])('set rejects a value in argv without repeating it', async (argument) => {
        const result = await runHog([...path, 'set', name, argument], base)
        expect(result.exitCode).toBe(EXIT_USAGE)
        expect(result.error()).toMatchObject({ code: 'usage_error', hint: expect.stringContaining('Pipe the value') })
        expect(result.requests.some(({ url }) => url.startsWith(api))).toBe(false)
        expectPrivate(result)
    })

    test.each(['', '🦔'.repeat(16385)])(
        'set rejects empty or oversized input before making a request',
        async (stdin) => {
            const result = await runHog([...path, 'set', name, '-'], { ...base, stdin })
            expect(result.exitCode).toBe(EXIT_USAGE)
            expect(result.error().code).toBe('invalid_secret_value')
            expect(result.requests.some(({ url }) => url.startsWith(api))).toBe(false)
        }
    )

    test('an agent with a terminal cannot echo a secret through an unmasked stdin read', async () => {
        const result = await runHog([...path, 'set', name, '-'], {
            ...base,
            env: { ...TEST_CREDENTIALS, HOG_AGENT: '1' },
            stdinIsTTY: true,
            stdoutIsTTY: true,
            stdin: secret,
        })
        expect(result.exitCode).toBe(EXIT_USAGE)
        expect(result.error().code).toBe('secret_input_required')
        expect(result.promptMessages).toEqual([])
        expect(result.requests.some(({ url }) => url.startsWith(api))).toBe(false)
        expectPrivate(result)
    })

    test.each(['service error', 'transport error'])(
        'set keeps private input out of %s and telemetry',
        async (failure) => {
            const result = await runHog([...path, 'set', name, '-', '--debug', '--raw'], {
                ...base,
                stdin: secret,
                respond: (url) => {
                    if (!url.startsWith(api)) {
                        return { status: 200, body: {} }
                    }
                    if (failure === 'transport error') {
                        throw new Error(secret)
                    }
                    return { status: 400, body: { type: secret, code: secret, detail: secret, attr: secret } }
                },
            })
            expect(result.exitCode).toBe(1)
            expectPrivate(result)
        }
    )

    test.each([true, false])('list shows names and last-set dates (tty=$0)', async (tty) => {
        const result = await runHog([...path, 'list', ...(tty ? [] : ['--raw'])], {
            ...base,
            stdoutIsTTY: tty,
            respond: (url) =>
                url === api
                    ? { status: 200, body: { results: [{ name, updated_at, value: secret }], value: secret } }
                    : { status: 200, body: {} },
        })
        expect(result.exitCode).toBe(EXIT_SUCCESS)
        if (tty) {
            expect(result.stdout).toContain(name)
            expect(result.stdout).toContain('2026-11-21')
        } else {
            expect(result.json()).toEqual({ secrets: [{ name, updated_at }] })
        }
        expect(result.requests.filter(({ url }) => url.startsWith(api))).toEqual([
            { method: 'GET', url: api, body: undefined },
        ])
        expectPrivate(result)
    })

    test.each([true, false])('remove only names the deleted secret (tty=$0)', async (tty) => {
        const result = await runHog([...path, 'remove', name], {
            ...base,
            stdoutIsTTY: tty,
            respond: (url) => (url.startsWith(api) ? { status: 204, body: undefined } : { status: 200, body: {} }),
        })
        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(result.requests.filter(({ url }) => url.startsWith(api))).toEqual([
            { method: 'DELETE', url: `${api}${name}/`, body: undefined },
        ])
        if (tty) {
            expect(result.stdout).toContain(`Removed secret ${name}`)
        } else {
            expect(result.json()).toEqual({ name })
        }
        expectPrivate(result)
    })

    test('the command manifest exposes the private input and per-operation scopes', async () => {
        const run = await runHog(['commands'])
        const commands = run.json(
            z.object({
                commands: z.array(
                    z.object({
                        name: z.string(),
                        scopes: z.array(z.string()),
                        arguments: z.array(z.unknown()),
                    })
                ),
            })
        ).commands
        expect(
            commands.filter((cmd) => cmd.name.startsWith('stack secret')).map(({ name, scopes }) => [name, scopes])
        ).toEqual([
            ['stack secret set', ['stack:write']],
            ['stack secret list', ['stack:read']],
            ['stack secret remove', ['stack:write']],
        ])
        expect(commands.find((cmd) => cmd.name === 'stack secret set')?.arguments).toContainEqual(
            expect.objectContaining({
                stdin: true,
                stdinOnly: true,
                required: false,
            })
        )
    })
})
