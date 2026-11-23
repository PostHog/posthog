import { describe, expect, test } from 'bun:test'

import { EXIT_CHANGES, EXIT_FAILURE, EXIT_NEEDS_PERSON, EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import type { Diff } from '@/stack/service'
import { runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

const id = '4cc121b9-b33e-4b8e-a864-bdee104132d8'
const commit = 'a'.repeat(40)
const base = 'https://ph.example.com/api/projects/7/stacks/web/diffs/'
const details = `${base}${id}/`
const source = { repository: 'sample/web', branch: 'feature', commit }
const counts = { create: 0, update: 0, recreate: 0, remove: 0, adopt: 0, rename: 0, release: 0 }
const diff: Diff = {
    changes: [
        {
            action: 'recreate',
            kind: 'model',
            key: 'revenue',
            name: 'Revenue',
            summary: 'Query changed',
            fields: [{ path: 'query', before: 'old', after: 'new', sensitive: false }],
            source: { file: '.ph/models.ts' },
            loses: 'Earlier results',
        },
    ],
    summary: { ...counts, recreate: 1 },
    drift: [{ kind: 'flag', key: 'menu', fields: [{ path: 'name', pushed: 'Menu', found: 'Navigation' }] }],
    errors: [],
    warnings: [],
}
const warned: Diff = {
    ...diff,
    warnings: [
        {
            code: 'possible_unrecorded_create',
            kind: 'dashboard',
            key: 'revenue board',
            message: 'A dashboard with this name exists and no stack manages it.',
            entities: [{ entity_id: '41', name: 'Revenue' }],
        },
        {
            code: 'unrecorded_creates_unchecked',
            kind: 'cohort',
            key: null,
            message: 'PostHog could not read every cohort. Check them in PostHog.',
            entities: [],
        },
    ],
}
const description = { version: 1 as const, resources: [] }
const files = {
    '/work/posthog.json': JSON.stringify({ stacks: { web: { dir: '.ph' } } }),
    '/work/.ph/index.ts': 'export {}',
}
const fake: FakeRuntimeOptions = {
    env: TEST_CREDENTIALS,
    files,
    evaluateStack: async () => ({
        description,
        typeCheck: { status: 'passed' },
        problems: [],
        output: { stdout: '', stderr: '' },
    }),
    readCommand: async ([, command]) => ({
        exitCode: 0,
        stdout:
            command === 'remote'
                ? 'https://user:token@git.example.com/sample/web.git?key=secret'
                : command === 'branch'
                  ? 'feature'
                  : commit,
        stderr: '',
    }),
}
const running = {
    id,
    stack_name: 'web',
    status: 'running',
    diff: null,
    source,
    created_at: '2026-11-21T11:00:00Z',
    expires_at: '2026-11-22T11:00:00Z',
    push_status: null,
    push_errors: [],
}
const ready = { ...running, status: 'ready', diff }
const pushed = { ...ready, status: 'pushed', push_status: 'succeeded' }
function response(body: unknown, status = 200): { body: unknown; status: number } {
    return { body, status }
}

describe('hog diff', () => {
    test('sends the order a definition needs with the description', async () => {
        const ordered = {
            version: 1 as const,
            resources: [
                {
                    kind: 'model',
                    key: 'by_plan',
                    body: { name: 'by_plan' },
                    depends_on: [{ kind: 'model', key: 'mrr' }],
                },
            ],
        }
        const run = await runHog(['diff'], {
            ...fake,
            evaluateStack: async () => ({
                description: ordered,
                typeCheck: { status: 'passed' },
                problems: [],
                output: { stdout: '', stderr: '' },
            }),
            respond: () => response(ready, 202),
        })
        expect(run.requests[0]).toMatchObject({ method: 'POST', body: { description: ordered } })
    })
    test('a 202 with an already failed diff reports the missing name immediately', async () => {
        const problem = { code: 'secret_missing', message: 'This stack holds no secret named API_TOKEN.' }
        const run = await runHog(['diff'], {
            ...fake,
            respond: () => response({ ...ready, status: 'failed', diff: { ...diff, errors: [problem] } }, 202),
        })
        expect(run.error()).toMatchObject({
            code: 'secret_missing',
            message: expect.stringContaining('API_TOKEN'),
            hint: expect.stringContaining('hog stack secret set'),
        })
        expect(run.requests.map(({ method }) => method)).toEqual(['POST'])
    })
    test.each([true, false])('a refused literal secret stays out of every diagnostic, tty=%p', async (tty) => {
        const literal = 'synthetic-secret-diagnostic-sentinel'
        const error = { code: 'secret_literal', message: `Invalid credential: ${literal}`, path: 'credentials' }
        const run = await runHog(['diff', '--wait', id, '--raw'], {
            ...fake,
            stdoutIsTTY: tty,
            respond: () => response({ ...ready, status: 'failed', diff: { ...diff, errors: [error] } }),
        })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.stderr).toContain('hog stack secret set NAME')
        expect(run.stderr + run.stdout).not.toContain(literal)
        if (!tty) {
            expect(run.error()).toMatchObject({
                code: 'secret_literal',
                problems: [{ code: 'secret_literal', path: 'credentials' }],
            })
        }
    })
    test.each([true, false])('shows hidden values and retains the entity ID for adoption, tty=%p', async (tty) => {
        const review = {
            ...ready,
            diff: {
                ...diff,
                changes: [
                    {
                        action: 'adopt',
                        kind: 'action',
                        key: 'pay',
                        entity_id: '27',
                        name: 'Pay',
                        fields: [{ path: 'name', before: null, after: null, sensitive: false }],
                        source: { file: '.ph/people.ts' },
                        summary: 'Use existing action',
                        loses: null,
                    },
                ],
                drift: [{ kind: 'action', key: 'pay', fields: [{ path: 'name', pushed: null, found: null }] }],
                summary: { ...counts, adopt: 1 },
            },
        }
        const run = await runHog(['diff', '--wait', id], { ...fake, stdoutIsTTY: tty, respond: () => response(review) })
        expect(run.exitCode).toBe(EXIT_CHANGES)
        expect(run.stdout).toContain('project admins')
        if (tty) {
            expect(run.stdout).toContain('Existing entity ID: 27')
            expect(run.stdout).toContain('name  (hidden)')
            expect(run.stdout).not.toContain('null')
        } else {
            expect(run.json()).toMatchObject({
                changes: [{ entity_id: '27', fields: [{ hidden: true, before: null, after: null }] }],
                drift: [{ fields: [{ hidden: true, pushed: null, found: null }] }],
            })
        }
    })

    test.each([true, false])('sends checked definitions and clean git coordinates, tty=%p', async (tty) => {
        const run = await runHog(['diff'], {
            ...fake,
            stdoutIsTTY: tty,
            respond: (url) => (url === base ? response(running, 202) : response(ready)),
        })
        expect(run.exitCode).toBe(EXIT_CHANGES)
        expect(run.requests).toEqual([
            { method: 'POST', url: base, body: { description, source } },
            { method: 'GET', url: details, body: undefined },
        ])
        if (tty) {
            expect(run.stdout).toContain('! recreate  model  revenue  Query changed  .ph/models.ts')
            expect(run.stdout).toContain('Loses: Earlier results')
            expect(run.stdout).toContain('Drift\n  flag menu  name  "Menu" → "Navigation"')
        } else {
            expect(run.json()).toEqual({
                id,
                status: 'ready',
                push: `hog push --diff ${id} --stack web`,
                ...diff,
                source,
            })
        }
    })

    test('an invalid definition stops before git or PostHog', async () => {
        const problem = {
            severity: 'error' as const,
            code: 'key_invalid',
            message: 'Choose a lowercase key.',
            key: 'Revenue',
            file: 'models.ts',
        }
        const run = await runHog(['diff'], {
            ...fake,
            evaluateStack: async () => ({
                description,
                typeCheck: { status: 'failed' },
                problems: [problem],
                output: { stdout: '', stderr: '' },
            }),
        })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.error()).toMatchObject({ code: 'stack_check_failed', problems: [problem] })
        expect(run.requests).toEqual([])
        expect(run.commands).toEqual([])
    })

    test('resumes a pending diff without submitting it again', async () => {
        const first = await runHog(['diff', '--comment'], { ...fake, respond: () => response(running) })
        expect(first.exitCode).toBe(EXIT_PENDING)
        expect(first.json()).toEqual({ id, status: 'running', next: `hog diff --wait ${id} --stack web --comment` })
        const done = await runHog(['diff', '--wait', id], {
            ...fake,
            respond: () => response({ ...ready, diff: { ...diff, changes: [], drift: [], summary: counts } }),
        })
        expect(done.exitCode).toBe(EXIT_SUCCESS)
        expect(done.requests.map(({ method }) => method)).toEqual(['GET'])
        expect(done.commands).toEqual([])
    })

    test('resumes the diff in the project selected by --env', async () => {
        const environments = {
            preview: { host: TEST_CREDENTIALS.HOG_HOST, project: 18 },
            live: { host: TEST_CREDENTIALS.HOG_HOST, project: 25 },
        }
        const run = await runHog(['diff', '--wait', id, '--env', 'preview'], {
            ...fake,
            files: {
                ...files,
                '/work/posthog.json': JSON.stringify({ stacks: { web: { dir: '.ph', environments } } }),
            },
            respond: () => response(ready),
        })
        expect(run.exitCode).toBe(EXIT_CHANGES)
        expect(run.requests.map((request) => request.url)).toEqual([details.replace('/projects/7/', '/projects/18/')])
        expect(run.json()).toMatchObject({ push: `hog push --diff ${id} --stack web --env preview` })
    })

    test.each(['POST', 'PATCH'])('uses %s to keep one review comment per stack', async (method) => {
        const env = {
            ...TEST_CREDENTIALS,
            GITHUB_REPOSITORY: 'sample/web',
            GITHUB_EVENT_PATH: '/event',
            GITHUB_TOKEN: 'test-token',
        }
        const marker = '<!-- hog-stack-diff 7 web - -->\n'
        const comments = [
            { id: 1, user: { login: 'contributor' }, body: marker },
            ...(method === 'PATCH' ? [{ id: 2, user: { login: 'github-actions[bot]' }, body: marker }] : []),
        ]
        const run = await runHog(['diff', '--wait', id, '--comment'], {
            ...fake,
            env,
            files: { ...files, '/event': '{"pull_request":{"number":12}}' },
            respond: (url, body, auth) => {
                if (url === details) {
                    return response(ready)
                }
                expect(auth).toBe('Bearer test-token')
                return response(body ? {} : comments)
            },
        })
        expect(run.exitCode).toBe(EXIT_CHANGES)
        const comment = String((run.requests.at(-1)?.body as { body: unknown }).body)
        expect(run.requests.at(-1)).toMatchObject({
            method,
            url: `https://api.github.com/repos/sample/web/issues/${method === 'PATCH' ? 'comments/2' : '12/comments'}`,
            body: { body: expect.stringContaining('PostHog changes in this pull request (stack web, project 7)') },
        })
        expect(comment).toContain('flag menu  name')
        expect(comment).not.toContain('Navigation')
        expect(comment).toContain('hog diff')
    })
})

describe('warnings after a push with an unknown outcome', () => {
    test.each([true, false])(
        'hog diff shows them above the changes with both ways forward, terminal=%p',
        async (tty) => {
            const run = await runHog(['diff', '--wait', id], {
                ...fake,
                stdoutIsTTY: tty,
                respond: () => response({ ...ready, diff: warned }),
            })
            expect(run.exitCode).toBe(EXIT_CHANGES)
            if (tty) {
                const warning = run.stdout.indexOf('may already have created these')
                expect(warning).toBeGreaterThan(-1)
                expect(warning).toBeLessThan(run.stdout.indexOf('recreate  model  revenue'))
                expect(run.stdout).toContain('ID 41  Revenue')
                expect(run.stdout).toContain('PostHog could not read every cohort')
                expect(run.stdout).toContain("hog stack adopt dashboard 'revenue board' 41 --stack web")
                expect(run.stdout).toContain(`hog stack reconcile --diff ${id} --stack web`)
                expect(run.stdout).toContain('Once a person reconciled the stack, push this diff')
            } else {
                expect(Object.keys(run.json() as object).slice(0, 3)).toEqual(['status', 'id', 'warnings'])
                expect(run.json()).toMatchObject({
                    warnings: [
                        {
                            code: 'possible_unrecorded_create',
                            entities: [{ entity_id: '41', name: 'Revenue' }],
                            adopt: ["hog stack adopt dashboard 'revenue board' 41 --stack web"],
                        },
                        { code: 'unrecorded_creates_unchecked', key: null, adopt: [] },
                    ],
                    reconcile: `hog stack reconcile --diff ${id} --stack web`,
                })
            }
        }
    )

    test('the pull request comment carries them too', async () => {
        const env = {
            ...TEST_CREDENTIALS,
            GITHUB_REPOSITORY: 'sample/web',
            GITHUB_EVENT_PATH: '/event',
            GITHUB_TOKEN: 'test-token',
        }
        const run = await runHog(['diff', '--wait', id, '--comment'], {
            ...fake,
            env,
            files: { ...files, '/event': '{"pull_request":{"number":12}}' },
            respond: (url, body) => (url === details ? response({ ...ready, diff: warned }) : response(body ? {} : [])),
        })
        expect(run.exitCode).toBe(EXIT_CHANGES)
        const comment = String((run.requests.at(-1)?.body as { body: unknown }).body)
        expect(comment).toContain('ID 41  Revenue')
        expect(comment).toContain('hog stack reconcile --diff')
        expect(comment).not.toContain('Navigation')
    })
})

describe('hog stack adopt', () => {
    const adopt = 'https://ph.example.com/api/projects/7/stacks/web/adopt/'
    const defined: FakeRuntimeOptions = {
        ...fake,
        evaluateStack: async () => ({
            description: {
                version: 1,
                resources: [{ kind: 'flag', key: 'new checkout', body: { key: 'new checkout' } }],
            },
            typeCheck: { status: 'passed' },
            problems: [],
            output: { stdout: '', stderr: '' },
        }),
    }
    const bound = { bindings: [{ kind: 'flag', key: 'new checkout', entity_id: '41', status: 'pending' }] }

    test.each([true, false])('binds an entity to a definition already in the folder, terminal=%p', async (tty) => {
        const run = await runHog(['stack', 'adopt', 'flag', 'new checkout', '41'], {
            ...defined,
            stdoutIsTTY: tty,
            respond: () => response(bound),
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.requests).toEqual([
            {
                method: 'POST',
                url: adopt,
                body: { resources: [{ kind: 'flag', key: 'new checkout', entity_id: '41' }] },
            },
        ])
        expect(run.files).toEqual(files)
        if (tty) {
            expect(run.stdout).toContain('Recorded a pending binding for flag new checkout')
            expect(run.stdout).toContain('The next push binds this entity to the definition and creates nothing for it')
        } else {
            expect(run.json()).toEqual({
                status: 'adopted',
                kind: 'flag',
                key: 'new checkout',
                entityId: '41',
                binding: 'pending',
                next: 'hog diff --stack web',
            })
        }
    })

    test('a key the folder does not define points to pull --adopt and asks nothing of PostHog', async () => {
        const run = await runHog(['stack', 'adopt', 'flag', 'menu', '41'], defined)
        expect(run.exitCode).toBe(EXIT_USAGE)
        expect(run.error()).toMatchObject({
            code: 'definition_missing',
            hint: expect.stringContaining('hog pull --adopt flag 41'),
        })
        expect(run.requests).toEqual([])
    })

    test.each([
        [404, 'entity_not_found', 'Check the ID in PostHog'],
        [409, 'entity_already_bound', 'already has a binding'],
        [409, 'key_already_bound', 'already bound to another entity'],
        [409, 'claimed_by_other_stack', 'Another stack manages this entity'],
    ] as const)('HTTP %d %s names the next step', async (status, code, hint) => {
        const run = await runHog(['stack', 'adopt', 'flag', 'new checkout', '41'], {
            ...defined,
            respond: () => response({ type: 'invalid_request', code, detail: 'Refused.', attr: null }, status),
        })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.error()).toMatchObject({ code, hint: expect.stringContaining(hint) })
    })
})

describe('hog stack reconcile', () => {
    const reconcile = 'https://ph.example.com/api/projects/7/stacks/web/reconcile/'
    const accepted = { stack_name: 'web', diff_id: id, acknowledged_warnings: 2 }

    test.each([
        { answers: ['yes'], posted: true },
        { answers: ['no'], posted: false },
    ])('a person sees the warnings and decides (answers $answers)', async ({ answers, posted }) => {
        const run = await runHog(['stack', 'reconcile', '--diff', id], {
            ...fake,
            stdoutIsTTY: true,
            answers: [...answers],
            respond: (url) => (url === reconcile ? response(accepted) : response({ ...ready, diff: warned })),
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.promptMessages.join('\n')).toContain('ID 41  Revenue')
        expect(run.requests.filter(({ method }) => method === 'POST')).toEqual(
            posted ? [{ method: 'POST', url: reconcile, body: { diff_id: id } }] : []
        )
        expect(run.stdout).toContain(
            posted ? `hog push --diff ${id} --stack web can go ahead now` : 'Nothing reconciled'
        )
    })

    test('an agent or a pipe is sent to a person, and nothing is asked of PostHog', async () => {
        const run = await runHog(['stack', 'reconcile', '--diff', id], fake)
        expect(run.exitCode).toBe(EXIT_NEEDS_PERSON)
        expect(run.error()).toMatchObject({
            code: 'reconcile_needs_person',
            hint: expect.stringContaining(`ask them to run hog stack reconcile --diff ${id}`),
        })
        expect(run.requests).toEqual([])
    })

    test('the help says no option lets an agent do it', async () => {
        const run = await runHog(['stack', 'reconcile', '--help'], fake)
        expect(run.stdout).toContain('No option lets an agent or a script do it')
    })

    test.each([
        [409, 'nothing_to_reconcile', 'hog push --diff', EXIT_FAILURE],
        [409, 'stack_moved', 'hog diff again', EXIT_FAILURE],
        [409, 'diff_not_ready', 'hog diff --wait', EXIT_FAILURE],
        [409, 'stack_locked', 'Wait for it', EXIT_FAILURE],
        [404, 'diff_not_found', 'hog diff', EXIT_FAILURE],
        [403, 'credential_not_supported', 'hog auth login', EXIT_NEEDS_PERSON],
    ] as const)('HTTP %d %s names the next step', async (status, code, hint, exitCode) => {
        const run = await runHog(['stack', 'reconcile', '--diff', id], {
            ...fake,
            stdoutIsTTY: true,
            answers: ['yes'],
            respond: (url) =>
                url === reconcile
                    ? response({ type: 'invalid_request', code, detail: 'Refused.', attr: null }, status)
                    : response({ ...ready, diff: warned }),
        })
        expect(run.exitCode).toBe(exitCode)
        expect(run.stderr).toContain(hint)
        expect(run.requests.at(-1)).toMatchObject({ method: 'POST', url: reconcile })
    })
})

describe('hog push', () => {
    test('a personal API key without the scopes the definitions need is told which to add', async () => {
        const run = await runHog(['push', '--diff', id], {
            ...fake,
            respond: () =>
                response(
                    {
                        type: 'authentication_error',
                        code: 'permission_denied',
                        detail: 'Permission denied.',
                        attr: null,
                        extra: { required_scopes: ['insight:write', 'dashboard:read'] },
                    },
                    403
                ),
        })
        expect(run.exitCode).toBe(EXIT_NEEDS_PERSON)
        expect(run.error()).toMatchObject({
            code: 'permission_denied',
            scopes: ['insight:write', 'dashboard:read'],
            hint: expect.stringContaining('Settings > Personal API keys'),
        })
        expect(run.error().hint).toContain('insight:write, dashboard:read')
    })

    test('a scope challenge takes the step-up path every command uses', async () => {
        const run = await runHog(['push', '--diff', id], {
            ...fake,
            respond: () => ({
                status: 403,
                body: {
                    type: 'authentication_error',
                    code: 'permission_denied',
                    detail: 'Permission denied.',
                    attr: null,
                    extra: { required_scopes: ['insight:write'] },
                },
                headers: { 'WWW-Authenticate': 'Bearer error="insufficient_scope", scope="insight:write"' },
            }),
        })
        expect(run.exitCode).toBe(EXIT_NEEDS_PERSON)
        expect(run.error()).toMatchObject({
            code: 'step_up_required',
            scopes: ['insight:write'],
            hint: expect.stringContaining('hog auth add'),
        })
    })

    test('a write to a definition managed in code names the file to edit', async () => {
        const run = await runHog(['push', '--diff', id], {
            ...fake,
            respond: () =>
                response(
                    {
                        type: 'invalid_request',
                        code: 'managed_in_code',
                        detail: 'Managed in code.',
                        attr: null,
                        extra: {
                            stack: 'web',
                            repository: 'sample/web',
                            kind: 'flag',
                            source: { file: '.ph/flags.ts', export: 'menu' },
                            fields: ['name'],
                        },
                    },
                    409
                ),
        })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.error()).toMatchObject({
            code: 'managed_in_code',
            stack: 'web',
            repository: 'sample/web',
            fields: ['name'],
            hint: expect.stringContaining('Edit .ph/flags.ts (export menu) in sample/web'),
        })
    })

    test('an uncertain push requires a new diff even when the saved diff is stale', async () => {
        const run = await runHog(['push', '--wait', id], {
            ...fake,
            respond: () => response({ ...ready, status: 'stale', push_status: 'uncertain' }),
        })
        expect(run.exitCode).toBe(EXIT_NEEDS_PERSON)
        expect(run.error()).toMatchObject({
            code: 'push_uncertain',
            hint: expect.stringContaining('a person runs hog stack reconcile --diff'),
        })
        expect(run.requests.map((req) => req.method)).toEqual(['GET'])
    })
    test('a push that failed after saving progress reports its errors, not a moved stack', async () => {
        const problem = {
            code: 'body_invalid',
            message: 'PostHog rejected a field in this definition.',
            kind: 'flag',
            key: 'menu',
        }
        const run = await runHog(['push', '--wait', id], {
            ...fake,
            respond: () => response({ ...ready, status: 'stale', push_status: 'failed', push_errors: [problem] }),
        })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.error()).toMatchObject({
            code: 'body_invalid',
            message: expect.stringContaining('flag menu'),
            problems: [problem],
        })
    })
    test.each([
        { name: 'a person who confirms raises it', tty: true, answers: ['yes'], exitCode: EXIT_SUCCESS, pushed: true },
        { name: 'a person who declines keeps it', tty: true, answers: ['no'], exitCode: EXIT_SUCCESS, pushed: false },
        {
            name: 'an agent or a pipe cannot raise it',
            tty: false,
            answers: [],
            exitCode: EXIT_NEEDS_PERSON,
            pushed: false,
        },
    ])('the removal limit: $name', async ({ tty, answers, exitCode, pushed: started }) => {
        let pushedYet = false
        const run = await runHog(['push', '--diff', id, '--max-removals', '7'], {
            ...fake,
            stdoutIsTTY: tty,
            answers: [...answers],
            respond: (url) => {
                if (url.endsWith('/push/')) {
                    pushedYet = true
                    return response(running)
                }
                return response(pushedYet ? pushed : ready)
            },
        })
        expect(run.exitCode).toBe(exitCode)
        expect(run.requests.filter(({ method }) => method === 'POST')).toEqual(
            started ? [{ method: 'POST', url: `${details}push/`, body: { max_removals: 7 } }] : []
        )
        if (tty) {
            expect(run.promptMessages.join('\n')).toContain('recreate  model  revenue  Loses: Earlier results')
        } else {
            expect(run.requests).toEqual([])
            expect(run.error()).toMatchObject({
                code: 'max_removals_needs_person',
                hint: expect.stringContaining(`Ask a person to run hog push --diff ${id} --max-removals 7`),
            })
        }
    })

    test.each([true, false])('pushes only the reviewed diff and reports changes, tty=%p', async (tty) => {
        const run = await runHog(['push', '--diff', id], {
            ...fake,
            stdoutIsTTY: tty,
            respond: (url) => response(url.endsWith('/push/') ? running : pushed),
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.requests).toEqual([
            { method: 'POST', url: `${details}push/`, body: {} },
            { method: 'GET', url: details, body: undefined },
        ])
        if (tty) {
            expect(run.stdout).toContain('1 recreated')
            expect(run.stdout).toContain('recreated  model  revenue')
        } else {
            expect(run.json()).toEqual({ id, status: 'pushed', summary: diff.summary, changes: diff.changes })
        }
    })

    test('a pipe needs --diff before any network call', async () => {
        const run = await runHog(['push'], fake)
        expect(run.exitCode).toBe(EXIT_USAGE)
        expect(run.error().hint).toContain('hog push --diff')
        expect(run.requests).toEqual([])
    })

    test.each(['yes', 'no'])('a person can review and answer %s to pushing the computed diff', async (answer) => {
        let started = false
        const run = await runHog(['push'], {
            ...fake,
            stdoutIsTTY: true,
            answers: [answer],
            respond: (url) => {
                if (url.endsWith('/push/')) {
                    started = true
                    return response(running)
                }
                return response(url === base ? running : started ? pushed : ready)
            },
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.stdout).toContain(answer === 'yes' ? 'Pushed diff' : 'Push cancelled')
        expect(started).toBe(answer === 'yes')
    })

    test.each([
        [409, 'stack_moved', 'hog diff again', EXIT_FAILURE],
        [400, 'too_many_removals', 'Ask a person', EXIT_NEEDS_PERSON],
    ] as const)('HTTP %d %s names the next step and who takes it', async (status, code, hint, exitCode) => {
        const run = await runHog(['push', '--diff', id], {
            ...fake,
            respond: () => response({ code, detail: 'Push refused.' }, status),
        })
        expect(run.exitCode).toBe(exitCode)
        expect(run.error()).toMatchObject({ code, hint: expect.stringContaining(hint) })
    })

    test("PostHog's reason is not repeated when it restates the message", async () => {
        const detail = 'The stack changed since this diff was made. Run diff again and push the new diff.'
        const run = await runHog(['push', '--diff', id], {
            ...fake,
            respond: () => response({ code: 'stack_moved', detail }, 409),
        })
        expect(run.error().message).toBe(detail)
    })

    test('a pending push resumes without a second push', async () => {
        const first = await runHog(['push', '--diff', id], {
            ...fake,
            respond: () => response({ ...running, push_status: 'running' }),
        })
        expect(first.exitCode).toBe(EXIT_PENDING)
        expect(first.json()).toMatchObject({ id, status: 'running', next: `hog push --wait ${id} --stack web` })
        const done = await runHog(['push', '--wait', id], { ...fake, respond: () => response(pushed) })
        expect(done.exitCode).toBe(EXIT_SUCCESS)
        expect(done.requests.map(({ method }) => method)).toEqual(['GET'])
    })
})
