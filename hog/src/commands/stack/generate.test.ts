import { describe, expect, test } from 'bun:test'

import { EXIT_CHANGES, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import { runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

const modules = 'https://ph.example.com/api/projects/7/stacks/modules/'
const description = {
    version: 1 as const,
    resources: [{ kind: 'event', key: 'checkout_completed', body: { name: 'checkout_completed' } }],
}
const generated = 'class CheckoutCompleted:\n    pass\n'
const out = '/work/app/events.py'
const files = { '/work/posthog.json': '{"stacks":{"web":{"dir":".ph"}}}', '/work/.ph/index.ts': 'export {}' }

function fake(existing?: string): FakeRuntimeOptions {
    return {
        env: TEST_CREDENTIALS,
        files: existing === undefined ? files : { ...files, [out]: existing },
        evaluateStack: async () => ({
            description,
            typeCheck: { status: 'passed' },
            problems: [],
            output: { stdout: '', stderr: '' },
        }),
        respond: (url) => {
            if (url === modules) {
                return {
                    status: 200,
                    body: {
                        content: generated,
                        language: 'python',
                        event_count: 1,
                        schema_hash: 'abc',
                        generator_version: '1',
                    },
                }
            }
            throw new Error(`Unexpected request to ${url}`)
        },
    }
}

const args = ['stack', 'generate', '--language', 'python', '--out', 'app/events.py']

describe('hog stack generate', () => {
    test.each([
        {
            name: 'creates a missing file',
            existing: undefined,
            flags: [],
            tty: false,
            answers: [],
            status: 'created',
            written: true,
        },
        {
            name: 'leaves a current file alone',
            existing: generated,
            flags: [],
            tty: false,
            answers: [],
            status: 'unchanged',
            written: true,
        },
        {
            name: 'only proposes replacing a file for an agent without --yes',
            existing: 'old',
            flags: [],
            tty: false,
            answers: [],
            status: 'proposed',
            written: false,
        },
        {
            name: 'replaces a file for an agent with --yes',
            existing: 'old',
            flags: ['--yes'],
            tty: false,
            answers: [],
            status: 'updated',
            written: true,
        },
        {
            name: 'replaces a file once a person confirms',
            existing: 'old',
            flags: [],
            tty: true,
            answers: ['yes'],
            status: 'updated',
            written: true,
        },
        {
            name: 'keeps a file when a person declines',
            existing: 'old',
            flags: [],
            tty: true,
            answers: ['no'],
            status: 'cancelled',
            written: false,
        },
        {
            name: 'writes nothing in a dry run',
            existing: undefined,
            flags: ['--dry-run'],
            tty: false,
            answers: [],
            status: 'proposed',
            written: false,
        },
    ])('$name', async ({ existing, flags, tty, answers, status, written }) => {
        const run = await runHog([...args, ...flags, ...(tty ? [] : ['-o', 'json'])], {
            ...fake(existing),
            stdoutIsTTY: tty,
            answers: [...answers],
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.requests.map(({ method, url, body }) => ({ method, url, body }))).toEqual([
            { method: 'POST', url: modules, body: { description, language: 'python' } },
        ])
        expect(run.files[out]).toBe(written ? generated : existing)
        if (!tty) {
            expect(run.json()).toMatchObject({
                status,
                path: 'app/events.py',
                eventCount: 1,
                ...(status === 'proposed' ? { next: expect.stringContaining('hog stack generate') } : {}),
            })
        }
    })

    test.each([
        { existing: generated, exitCode: EXIT_SUCCESS, status: 'current' },
        { existing: 'old', exitCode: EXIT_CHANGES, status: 'stale' },
        { existing: undefined, exitCode: EXIT_CHANGES, status: 'stale' },
    ])('--check reports a $status module and writes nothing', async ({ existing, exitCode, status }) => {
        const run = await runHog([...args, '--check', '--yes'], fake(existing))
        expect(run.exitCode).toBe(exitCode)
        expect(run.json()).toMatchObject({ status })
        expect(run.files[out]).toBe(existing)
    })

    test.each([['../outside/events.py'], ['/etc/events.py']])(
        'refuses %s, outside the repository, before asking PostHog',
        async (path) => {
            const run = await runHog(['stack', 'generate', '--language', 'python', '--out', path, '--yes'], fake())
            expect(run.exitCode).toBe(EXIT_USAGE)
            expect(run.error().code).toBe('generate_path_outside')
            expect(run.requests).toEqual([])
            expect(run.files).toEqual(files)
        }
    )
})
