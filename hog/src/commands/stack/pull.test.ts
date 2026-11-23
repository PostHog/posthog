import { describe, expect, test } from 'bun:test'

import { EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import type { StackDefinitions } from '@/stack/definitions'
import { runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

const files = {
    '/work/posthog.json': '{"stacks":{"web":{"dir":".ph"}}}',
    '/work/.ph/index.ts': "export * from './views'\n",
    '/work/.ph/views.ts': 'export {}',
}
const resource = { kind: 'action', key: 'checkout', body: { name: 'Checkout', steps: [] } }
const entity = { kind: 'action', entity_id: '17', ...resource.body, body: resource.body }
const binding = { kind: 'action', key: 'checkout', entity_id: '17' }
const page = { results: [entity], next: null, count: 1 }
const base = 'https://ph.example.com/api/projects/7/stacks/'
const field = { path: 'name', pushed: 'Checkout', found: 'Cart' }
const manual = { path: 'description', pushed: 'Trial', found: 'Paid' }
const drift = [{ kind: 'action', key: 'checkout', fields: [field, manual] }]
const counts = { create: 0, update: 0, recreate: 0, remove: 0, adopt: 0, rename: 0, release: 0 }
const saved = { id: 'run-1', status: 'ready', diff: { changes: [], summary: counts, errors: [], drift } }

const adapter: StackDefinitions = {
    naturalKey: () => undefined,
    generateDefinitions: (resources) => {
        expect(resources).toEqual([resource])
        return [
            { path: 'actions.ts', contents: 'export const checkout = {}\n' },
            { path: 'index.ts', contents: "export * from './actions'\n" },
        ]
    },
    async foldDrift(folder, fields) {
        expect(folder).toBe('/work/.ph')
        expect(fields).toEqual(drift)
        return {
            applied: [{ file: '.ph/views.ts', ...field }],
            manual: [{ file: '.ph/views.ts', ...manual }],
            edits: [{ target: '/work/.ph/views.ts', before: 'export {}', after: "export const name = 'Cart'" }],
        }
    },
}

function fake(): FakeRuntimeOptions {
    let checks = 0
    return {
        env: TEST_CREDENTIALS,
        files,
        stackDefinitions: adapter,
        evaluateStack: async () => ({
            description: { version: 1, resources: ++checks === 1 ? [] : [resource] },
            problems: [],
            typeCheck: { status: 'passed' },
            output: { stdout: '', stderr: '' },
        }),
        readCommand: async ([, cmd]) => ({
            stdout: cmd === 'rev-parse' ? 'a'.repeat(40) : cmd === 'remote' ? 'git@github.com:sample/web.git' : 'main',
            stderr: '',
            exitCode: 0,
        }),
        respond: (url) => {
            if (url.startsWith(base + 'adoptable/?')) {
                return { status: 200, body: page }
            }
            if (url === base + 'web/adopt/') {
                return { status: 200, body: { bindings: [{ ...binding, status: 'pending' }] } }
            }
            if (url === base + 'web/diffs/') {
                return { status: 202, body: { id: 'run-1', status: 'running' } }
            }
            if (url === base + 'web/diffs/run-1/') {
                return { status: 200, body: saved }
            }
            throw new Error('Unexpected request')
        },
    }
}

describe('hog pull', () => {
    test.each([true, false])('writes reviewed definitions and binds the selected ID, terminal=%p', async (tty) => {
        const run = await runHog(['pull', '--adopt', 'action', '17', ...(tty ? [] : ['--yes'])], {
            ...fake(),
            stdoutIsTTY: tty,
            answers: ['yes'],
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.files['/work/.ph/index.ts']).toBe("export * from './views'\nexport * from './actions'\n")
        expect(run.files['/work/.ph/actions.ts']).toContain('export const checkout')
        expect(run.requests.at(-1)).toEqual({
            method: 'POST',
            url: base + 'web/adopt/',
            body: { resources: [binding] },
        })
        if (tty) {
            expect(run.stdout).toContain('Recorded pending bindings')
        } else {
            expect(run.json()).toMatchObject({ status: 'adopted', bindings: [binding] })
        }
    })

    test.each([true, false])(
        'lists one page as PostHog pages it, with the command for the next one, terminal=%p',
        async (tty) => {
            const name = `${'checkout_completed_'.repeat(26)}x`.slice(0, 512)
            const run = await runHog(['pull', '--adopt', 'event', '--limit', '1', '--dry-run'], {
                ...fake(),
                stdoutIsTTY: tty,
                respond: () => ({
                    status: 200,
                    body: {
                        count: null,
                        previous: null,
                        next: 'https://ph.example.com/api/projects/7/stacks/adoptable/?kind=event&cursor=1&limit=1',
                        results: [{ kind: 'event', entity_id: '17', name, body: { name } }],
                    },
                }),
            })
            expect(run.exitCode).toBe(EXIT_SUCCESS)
            expect(run.requests.map(({ url }) => url)).toEqual([base + 'adoptable/?kind=event&limit=1'])
            if (tty) {
                expect(run.stdout).toContain('hog pull --adopt event --limit 1 --stack web --cursor 1')
                expect(run.stdout).toContain(name.slice(0, 20))
            } else {
                expect(run.json()).toEqual({
                    status: 'listed',
                    entities: [{ id: '17', name }],
                    nextCursor: '1',
                    next: 'hog pull --adopt event --limit 1 --stack web --cursor 1',
                })
            }
            expect(run.files).toEqual(files)
        }
    )

    test('lists the next page of any kind with the cursor returned by PostHog', async () => {
        const run = await runHog(['pull', '--adopt', 'flag', '--limit', '12', '--cursor', '100'], {
            ...fake(),
            respond: () => ({
                status: 200,
                body: {
                    count: null,
                    previous: null,
                    next: base + 'adoptable/?kind=flag&limit=12&cursor=112',
                    results: [],
                },
            }),
        })
        expect(run.exitCode).toBe(0)
        expect(run.requests[0]?.url).toBe(base + 'adoptable/?kind=flag&limit=12&cursor=100')
        expect(run.json()).toMatchObject({ nextCursor: '112', next: expect.stringContaining('--cursor 112') })
    })

    test('an opaque cursor with shell characters is returned as data only', async () => {
        const cursor = 'opaque $HOME'
        const respond = (): { status: number; body: unknown } => ({
            status: 200,
            body: {
                count: null,
                previous: null,
                next: base + 'adoptable/?cursor=' + encodeURIComponent(cursor),
                results: [],
            },
        })
        const agent = await runHog(['pull', '--adopt', 'flag'], { ...fake(), respond })
        expect(agent.json()).toMatchObject({ nextCursor: cursor, next: null })
        const person = await runHog(['pull', '--adopt', 'flag'], { ...fake(), stdoutIsTTY: true, respond })
        expect(person.stdout).toContain('nextCursor')
        expect(person.stdout).not.toContain(cursor)
    })

    test.each([
        { pushed: null, found: null },
        { pushed: { nested: '[redacted]' }, found: 'Current' },
    ])('withheld values cannot be folded into a literal definition ($pushed)', async ({ pushed, found }) => {
        const run = await runHog(['pull', '--wait', 'run-1'], {
            ...fake(),
            stackDefinitions: undefined,
            respond: () => ({
                status: 200,
                body: {
                    ...saved,
                    diff: {
                        ...saved.diff,
                        drift: [
                            {
                                kind: 'action',
                                key: resource.key,
                                fields: [{ path: 'name', pushed, found }],
                            },
                        ],
                    },
                },
            }),
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.json()).toMatchObject({
            applied: [],
            manual: [{ pushed: '(hidden)', found: '(hidden)', reason: expect.stringContaining('project admins') }],
        })
        expect(run.files).toEqual(files)
    })

    test('a visible change to null stays editable', async () => {
        const visible = [
            { kind: 'action', key: resource.key, fields: [{ path: 'description', pushed: 'Earlier', found: null }] },
        ]
        // PostHog sends `deleted: false` on every entity that still exists.
        const sent = visible.map((item) => ({ ...item, deleted: false }))
        const run = await runHog(['pull', '--wait', 'run-1'], {
            ...fake(),
            respond: () => ({ status: 200, body: { ...saved, diff: { ...saved.diff, drift: sent } } }),
            stackDefinitions: {
                ...adapter,
                async foldDrift(_folder, drift) {
                    expect(drift).toEqual(visible)
                    return { applied: [{ file: 'actions.ts', ...visible[0]!.fields[0]! }], manual: [], edits: [] }
                },
            },
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.json()).toMatchObject({ applied: [{ found: null }], manual: [] })
    })

    test('rolls back generated files that would introduce an extra definition before binding', async () => {
        let checks = 0
        const run = await runHog(['pull', '--adopt', 'action', '17', '--yes'], {
            ...fake(),
            evaluateStack: async () => ({
                description: {
                    version: 1,
                    resources: ++checks === 1 ? [] : [resource, { ...resource, key: 'unrelated' }],
                },
                typeCheck: { status: 'passed' },
                problems: [],
                output: { stdout: '', stderr: '' },
            }),
        })
        expect(run.error().code).toBe('adoption_check_failed')
        expect(run.files).toEqual(files)
        expect(run.requests.map(({ method }) => method)).toEqual(['GET'])
    })

    test.each([
        ['--dry-run', EXIT_SUCCESS],
        ['', EXIT_USAGE],
    ] as const)(
        'preserves a hand-edited family file and records no bindings without confirmation (%s)',
        async (flag, status) => {
            const before = { ...files, '/work/.ph/actions.ts': 'export const earlier = {}' }
            const run = await runHog(['pull', '--adopt', 'action', 'Checkout', ...(flag ? [flag] : [])], {
                ...fake(),
                files: before,
            })
            expect(run.exitCode).toBe(status)
            expect(run.files).toEqual(before)
            expect(run.requests.map(({ method }) => method)).toEqual(['GET'])
            if (flag) {
                expect(run.stdout).toContain('adopted/')
            }
        }
    )

    test.each([
        { name: 'a person who confirms', argv: [], tty: true, answers: ['yes'], written: true },
        { name: 'a person who declines', argv: [], tty: true, answers: ['no'], written: false },
        { name: 'an agent without --yes', argv: [], tty: false, answers: [], written: false },
        { name: 'an agent with --yes', argv: ['--yes'], tty: false, answers: [], written: true },
    ])(
        'shows each rewritten and manual field and rewrites the definitions only for $name',
        async ({ argv, tty, answers, written }) => {
            const run = await runHog(['pull', ...argv], { ...fake(), stdoutIsTTY: tty, answers: [...answers] })
            expect(run.exitCode).toBe(EXIT_SUCCESS)
            expect(run.requests.map(({ method }) => method)).toEqual(['POST', 'GET'])
            expect(run.files['/work/.ph/views.ts']).toBe(written ? "export const name = 'Cart'" : 'export {}')
            if (tty) {
                expect(run.promptMessages.join('\n')).toContain("+export const name = 'Cart'")
                if (written) {
                    expect(run.stdout).toContain('Rewrote  .ph/views.ts  name  "Checkout" → "Cart"')
                    expect(run.stdout).toContain('Edit  .ph/views.ts  description  "Trial" → "Paid"')
                    expect(run.stdout).toContain('hog diff keeps showing this drift until the next push')
                }
            } else if (written) {
                expect(run.json()).toEqual({
                    status: 'pulled',
                    id: 'run-1',
                    files: ['.ph/views.ts'],
                    applied: [{ file: '.ph/views.ts', ...field }],
                    manual: [{ file: '.ph/views.ts', ...manual }],
                    note: expect.stringContaining('until the next push'),
                })
            } else {
                expect(run.json()).toMatchObject({
                    status: 'proposed',
                    files: ['.ph/views.ts'],
                    next: 'hog pull --wait run-1 --stack web --yes',
                    changes: [expect.stringContaining("+export const name = 'Cart'")],
                })
            }
        }
    )

    test('a pending drift check resumes with the same ID and keeps dry-run', async () => {
        const run = await runHog(['pull', '--dry-run'], {
            ...fake(),
            respond: () => ({ status: 200, body: { id: 'run-1', status: 'running', diff: null } }),
        })
        expect(run.exitCode).toBe(EXIT_PENDING)
        expect(run.json()).toMatchObject({ id: 'run-1', next: 'hog pull --wait run-1 --stack web --dry-run' })
        const done = await runHog(['pull', '--wait', 'run-1', '--dry-run'], fake())
        expect(done.exitCode).toBe(EXIT_SUCCESS)
        expect(done.json()).toMatchObject({ status: 'drift', drift })
        expect(done.requests.map(({ method }) => method)).toEqual(['GET'])
    })

    test('a hidden value or a removed entity can only be handled manually', async () => {
        const drift = [
            {
                kind: 'action',
                key: 'checkout',
                fields: [{ path: 'token', sensitive: true, pushed: 'old-secret', found: 'new-secret' }],
            },
            { kind: 'flag', key: 'menu', deleted: true, fields: [] },
        ]
        const run = await runHog(['pull', '--wait', 'run-1'], {
            ...fake(),
            stackDefinitions: undefined,
            respond: () => ({ status: 200, body: { ...saved, diff: { ...saved.diff, drift } } }),
        })
        expect(run.exitCode).toBe(0)
        expect(run.json()).toMatchObject({
            applied: [],
            manual: [
                { kind: 'action', key: 'checkout', path: 'token', pushed: '(hidden)', found: '(hidden)' },
                { kind: 'flag', key: 'menu', path: 'binding', pushed: 'Present', found: 'Removed' },
            ],
        })
        expect(run.stdout).not.toContain('-secret')
    })

    test('a key shared by two kinds in one file needs a manual edit', async () => {
        const run = await runHog(['pull', '--wait', 'run-1'], {
            ...fake(),
            stackDefinitions: undefined,
            evaluateStack: async () => ({
                description: {
                    version: 1,
                    resources: ['action', 'cohort'].map((kind) => ({
                        ...resource,
                        kind,
                        source: { file: '.ph/people.ts' },
                    })),
                },
                typeCheck: { status: 'passed' },
                problems: [],
                output: { stdout: '', stderr: '' },
            }),
        })
        expect(run.exitCode).toBe(0)
        expect(run.json()).toMatchObject({
            applied: [],
            manual: [
                { file: '.ph/people.ts', ...field },
                { file: '.ph/people.ts', ...manual },
            ],
        })
    })
})
