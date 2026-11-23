import { describe, expect, test } from 'bun:test'

import { EXIT_NEEDS_PERSON, EXIT_SUCCESS } from '@/core/errors'
import { runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

const url = 'https://ph.example.com/api/projects/7/stacks/web/context_pages/'
const files = { '/work/posthog.json': '{"stacks":{"web":{"dir":".ph"}}}' }

function fake(admin = true): FakeRuntimeOptions {
    return {
        env: TEST_CREDENTIALS,
        files,
        respond: (requested, body) => {
            if (requested !== url) {
                throw new Error(`Unexpected request to ${requested}`)
            }
            if (!admin) {
                return {
                    status: 403,
                    body: {
                        type: 'authentication_error',
                        code: 'organization_admin_required',
                        detail: 'Only an organization admin can.',
                        attr: null,
                    },
                }
            }
            const { enabled } = body as { enabled: boolean }
            return { status: 200, body: { name: 'web', context_pages_enabled: enabled } }
        },
    }
}

describe('hog stack context-pages', () => {
    test.each([
        {
            name: 'a person who confirms turns them on',
            argv: ['enable'],
            tty: true,
            answers: ['yes'],
            sent: [{ enabled: true }],
            exitCode: EXIT_SUCCESS,
        },
        {
            name: 'a person who declines changes nothing',
            argv: ['enable'],
            tty: true,
            answers: ['no'],
            sent: [],
            exitCode: EXIT_SUCCESS,
        },
        {
            name: 'an agent without --yes needs a person',
            argv: ['enable'],
            tty: false,
            answers: [],
            sent: [],
            exitCode: EXIT_NEEDS_PERSON,
        },
        {
            name: 'an agent with --yes turns them on',
            argv: ['enable', '--yes'],
            tty: false,
            answers: [],
            sent: [{ enabled: true }],
            exitCode: EXIT_SUCCESS,
        },
        {
            name: 'disable turns them off',
            argv: ['disable'],
            tty: false,
            answers: [],
            sent: [{ enabled: false }],
            exitCode: EXIT_SUCCESS,
        },
    ])('$name', async ({ argv, tty, answers, sent, exitCode }) => {
        const run = await runHog(['stack', 'context-pages', ...argv], {
            ...fake(),
            stdoutIsTTY: tty,
            answers: [...answers],
        })
        expect(run.exitCode).toBe(exitCode)
        expect(run.requests.map(({ body }) => body)).toEqual([...sent] as unknown[])
        if (tty) {
            expect(run.promptMessages.join('\n')).toContain('every project in it shares them')
        } else if (exitCode === EXIT_NEEDS_PERSON) {
            expect(run.error()).toMatchObject({
                code: 'confirmation_required',
                hint: expect.stringContaining('organization admin'),
            })
        }
    })

    test('the help says what turning them on means', async () => {
        const run = await runHog(['stack', 'context-pages', 'enable', '--help'], { files })
        expect(run.stdout).toContain('every project in it shares them')
        expect(run.stdout).toContain('organization-wide read and write scopes')
    })

    test('someone who is not an organization admin is told who can', async () => {
        const run = await runHog(['stack', 'context-pages', 'enable', '--yes'], fake(false))
        expect(run.exitCode).toBe(EXIT_NEEDS_PERSON)
        expect(run.error()).toMatchObject({
            code: 'organization_admin_required',
            hint: expect.stringContaining('Ask an organization admin'),
        })
    })
})
