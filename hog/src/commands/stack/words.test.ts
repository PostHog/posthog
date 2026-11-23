import { expect, test } from 'bun:test'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import ts from 'typescript'

import { EXIT_CHANGES, EXIT_FAILURE, EXIT_NEEDS_PERSON, EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import type { Evaluation } from '@/stack/evaluation'
import { actions, type Diff } from '@/stack/service'
import { runHog, TEST_CREDENTIALS, type FakeRuntimeOptions, type HogRun } from '@/testing'

const forbidden = /\b(?:terraform|opentofu|tofu|provider|state|plan|apply|hcl|resource address)\b/i
const untranslated = 'Terraform OpenTofu tofu Provider State Plan Apply HCL resource address'
const id = '94ce3a72-8501-4d6a-bed2-7402175bd164'
const sha = '1'.repeat(40)
const files = {
    '/work/posthog.json': '{"stacks":{"web":{"dir":".ph"}}}',
    '/work/.ph/index.ts': 'export {}\n',
    '/event': '{"pull_request":{"number":3}}',
}
const resource = { kind: 'action', key: 'signup', body: { name: 'Signup' } }
const evaluation: Evaluation = {
    typeCheck: { status: 'passed', compiler: '6.0.3' },
    description: { version: 1, resources: [resource] },
    output: { stdout: 'Loaded definitions', stderr: 'Reading views' },
    problems: [],
}
const field = { path: 'name', pushed: 'First', found: 'Second' }
const report: Diff = {
    changes: actions.map((action) => ({
        action,
        kind: 'flag',
        key: action,
        name: 'Menu',
        summary: 'New name',
        source: { file: '.ph/flags.ts' },
        fields: [],
        loses: action === 'recreate' ? 'Links and history' : null,
    })),
    drift: [{ kind: 'flag', key: 'menu', fields: [field] }],
    errors: [],
    summary: { create: 1, update: 1, recreate: 1, remove: 1, adopt: 1, rename: 1, release: 1 },
    notes: ['Review the changes before pushing.'],
    warnings: [
        {
            code: 'possible_unrecorded_create',
            kind: 'flag',
            key: 'create',
            message: 'A flag with this key exists and no stack manages it.',
            entities: [{ entity_id: '9', name: 'Menu' }],
        },
        {
            code: 'unrecorded_creates_unchecked',
            kind: 'cohort',
            key: null,
            message: 'Check the cohorts in PostHog by hand.',
            entities: [],
        },
    ],
}
const warningCodes = ['possible_unrecorded_create', 'unrecorded_creates_unchecked']
const base: FakeRuntimeOptions = {
    files,
    env: { ...TEST_CREDENTIALS, GITHUB_REPOSITORY: 'example/web', GITHUB_TOKEN: 'test', GITHUB_EVENT_PATH: '/event' },
    evaluateStack: async () => evaluation,
    readCommand: async ([, command]) => ({
        exitCode: 0,
        stderr: '',
        stdout: command === 'remote' ? 'https://github.com/example/web.git' : command === 'branch' ? 'feature' : sha,
    }),
    stackDefinitions: {
        naturalKey: () => undefined,
        generateDefinitions: () => [{ path: 'actions.ts', contents: 'export const signup = {}\n' }],
        foldDrift: async () => ({
            applied: [{ file: 'flags.ts', ...field }],
            manual: [{ file: 'views.ts', ...field }],
            edits: [{ target: '/work/.ph/index.ts', before: 'export {}\n', after: "export const menu = 'Second'\n" }],
        }),
    },
}

const codesFromDiffAndPush = [
    'stack_moved',
    'stack_locked',
    'removal_blocked',
    'reference_cycle',
    'reference_missing',
    'credentials_invalid',
    'entity_missing',
    'entity_exists',
    'body_invalid',
    'connection_timeout',
    'stack_interrupted',
    'invalid_definition',
    'stack_failed',
    'binding_unknown',
    'binding_conflict',
    'claimed_by_other_stack',
    'kind_unsupported',
    'snapshot_invalid',
    'target_invalid',
    'runner_unavailable',
    'mirror_missing',
    'secret_missing',
    'lookup_failed',
    'run_timeout',
    'run_failed',
    'caller_unavailable',
    'push_interrupted',
    'credentials_missing',
    'file_conflict',
    'snapshot_missing',
    'input_invalid',
    'record_save_failed',
    'entity_read_invalid',
    'push_uncertain',
    'record_missing',
    'run_timed_out',
    'secret_literal',
    'managed_in_code',
    'context_layer_not_enabled',
    'context_page_managed_twice',
    'context_page_write_uncertain',
    'context_pages_not_enabled',
]
const forPerson = [
    'user_required',
    'missing_scopes',
    'permission_denied',
    'too_many_removals',
    'push_uncertain',
    'organization_admin_required',
    'context_pages_not_enabled',
    'context_layer_not_enabled',
    'context_page_write_uncertain',
    'repository_not_connected',
    'credential_not_supported',
]
const codesFromHttp: Record<number, string[]> = {
    400: [
        'invalid_stack_name',
        'kind_not_adoptable',
        'too_many_removals',
        'invalid_secret_name',
        'secret_too_large',
        'invalid_key',
        'duplicate_definition',
        'too_many_definitions',
        'definition_too_large',
        'definition_too_deep',
        'secret_literal',
        'invalid_definition',
        'kind_unsupported',
        'invalid_input',
        'context_pages_not_enabled',
        'kind_not_listable',
    ],
    403: [
        'user_required',
        'missing_scopes',
        'permission_denied',
        'impersonated_push',
        'caller_unavailable',
        'organization_admin_required',
        'credential_not_supported',
    ],
    404: ['stack_not_found', 'diff_not_found', 'binding_not_found', 'secret_not_found', 'entity_not_found'],
    409: [
        'stack_moved',
        'stack_locked',
        'diff_pushed',
        'diff_not_ready',
        'diff_expired',
        'entity_already_bound',
        'claimed_by_other_stack',
        'key_already_bound',
        'managed_in_code',
        'push_uncertain',
        'repository_not_connected',
        'tasks_unavailable',
        'nothing_to_reconcile',
    ],
    503: ['stacks_unavailable', 'runner_unavailable'],
}

function serviceErrorCodes(): Set<string> {
    const root = join(import.meta.dir, '../../../../products/stacks/backend')
    const found = new Set<string>()
    for (const name of new Bun.Glob('**/*.py').scanSync({ cwd: root })) {
        if (name.split(/[\\/]/).some((part) => part === 'tests' || part === 'migrations')) {
            continue
        }
        const code = readFileSync(join(root, name), 'utf8')
        const sites = /(?:StackErrorKind\.\w+,\s*|"code":\s*|_error\(\s*|code=)"([a-z][a-z0-9_]*)"/g
        for (const match of code.matchAll(sites)) {
            found.add(match[1]!)
        }
        if (name.replaceAll('\\', '/') === 'facade/enums.py') {
            const enumBody = code.match(/^class StackErrorCode\([^)]*\):\n((?:[ \t].*\n|\n)*)/m)?.[1]
            expect(enumBody).toBeDefined()
            for (const match of enumBody!.matchAll(/^\s*[A-Z_]+\s*=\s*"([a-z_]+)"/gm)) {
                found.add(match[1]!)
            }
        }
        if (name.endsWith('translate_out.py')) {
            const rules = code.match(/_ERROR_RULES = ([\s\S]*?)_UNRECOGNIZED/)?.[1]
            expect(rules).toBeDefined()
            for (const match of rules!.matchAll(/\(\s*"([a-z_]+)",\s*r"/g)) {
                found.add(match[1]!)
            }
        }
    }
    expect(found.has('too_many_removals')).toBe(true)
    expect(found.has('reference_cycle')).toBe(true)
    return found
}

const answer = (body: unknown, status = 200): { body: unknown; status: number } => ({ body, status })
const running = { id, status: 'running', diff: null }
const ready = { id, status: 'ready', diff: report }
const entity = { kind: 'action', name: 'Signup', entity_id: '17', body: resource.body }
const binding = { kind: 'action', key: 'signup', entity_id: '17', status: 'pending' }

const serve: NonNullable<FakeRuntimeOptions['respond']> = (url, body) => {
    if (url.startsWith('https://api.github.com')) {
        return answer(body ? {} : [])
    }
    if (url.includes('/adoptable/')) {
        return answer({ results: [entity], next: null })
    }
    if (url.endsWith('/adopt/')) {
        return answer({ bindings: [binding] })
    }
    if (url.endsWith('/diffs/') || url.endsWith('/push/')) {
        return answer(running, 202)
    }
    return answer(ready)
}

// Some errors need an OS failure or another writer between two syscalls. Include their authored messages without faking filesystem races.
function errorLiterals(): string[] {
    const copy: string[] = []
    function visit(node: ts.Node): void {
        if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'HogError') {
            const literals = (arg: ts.Node): void => {
                if (
                    ts.isStringLiteralLike(arg) ||
                    ts.isTemplateHead(arg) ||
                    ts.isTemplateMiddle(arg) ||
                    ts.isTemplateTail(arg)
                ) {
                    copy.push(arg.text)
                } else {
                    ts.forEachChild(arg, literals)
                }
            }
            for (const arg of node.arguments ?? []) {
                literals(arg)
            }
        }
        ts.forEachChild(node, visit)
    }
    for (const dir of [import.meta.dir, join(import.meta.dir, '../../stack')]) {
        for (const name of readdirSync(dir).filter((file) => file.endsWith('.ts') && !file.endsWith('.test.ts'))) {
            visit(ts.createSourceFile(name, readFileSync(join(dir, name), 'utf8'), ts.ScriptTarget.Latest, false))
        }
    }
    return copy
}

test('stack commands, prompts, guides, diagnostics and pull request comments use the public vocabulary', async () => {
    const exercised = new Set([...codesFromDiffAndPush, ...Object.values(codesFromHttp).flat(), ...warningCodes])
    expect([...serviceErrorCodes()].filter((code) => !exercised.has(code))).toEqual([])
    const printed: string[] = errorLiterals()
    async function collect(
        args: string[],
        tty: boolean,
        code: number,
        options: FakeRuntimeOptions = {}
    ): Promise<HogRun> {
        const run = await runHog(args, { ...base, respond: serve, ...options, stdoutIsTTY: tty })
        expect({ args, exitCode: run.exitCode, reason: run.exitCode === code ? '' : run.stderr }).toEqual({
            args,
            exitCode: code,
            reason: '',
        })
        printed.push(run.stdout, run.stderr, ...run.promptMessages)
        for (const [path, text] of Object.entries(run.files)) {
            if (path.endsWith('/AGENTS.md') || path.includes('/.github/workflows/')) {
                printed.push(text)
            }
        }
        for (const call of run.requests.filter(
            (req) => req.url.startsWith('https://api.github.com') && req.method !== 'GET'
        )) {
            printed.push(JSON.stringify(call.body))
        }
        return run
    }

    for (const tty of [false, true]) {
        // Every command the stack commands, their hints and the generated files tell a person to run.
        const named = [
            ['stack'],
            ...['check', 'diff', 'push', 'pull', 'init'].map((command) => ['stack', command]),
            ...['set', 'list', 'remove'].map((command) => ['stack', 'secret', command]),
            ['stack', 'generate'],
            ['stack', 'reconcile'],
            ['stack', 'adopt'],
            ['stack', 'context-pages'],
            ['stack', 'context-pages', 'enable'],
            ['stack', 'context-pages', 'disable'],
            ['ci', 'setup'],
            ['auth', 'login'],
            ['config', 'check'],
        ]
        for (const command of named) {
            await collect([...command, '--help'], tty, EXIT_SUCCESS)
        }
        await collect(['check'], tty, EXIT_SUCCESS)
        await collect(['check', '--raw'], tty, EXIT_SUCCESS)
        await collect(['check'], tty, EXIT_FAILURE, {
            evaluateStack: async () => ({
                ...evaluation,
                typeCheck: { status: 'skipped' },
                problems: [
                    {
                        severity: 'error',
                        code: 'invalid_definition',
                        message: 'Choose a valid key.',
                        file: 'flags.ts',
                        line: 2,
                    },
                    {
                        severity: 'warning',
                        code: 'definition_warning',
                        message: 'Check the name.',
                        kind: 'flag',
                        key: 'menu',
                    },
                ],
            }),
        })
        await collect(['check', '--stack', 'constructor'], tty, EXIT_USAGE)
        await collect(['check', '--env', 'preview'], tty, EXIT_USAGE)
        await collect(['init', '--stack', 'web'], tty, EXIT_SUCCESS, { files: {} })
        await collect(['init', '--stack', 'web', '--dry-run'], tty, EXIT_SUCCESS, { files: {} })
        await collect(['init', '--stack', 'web'], tty, EXIT_SUCCESS)
        await collect(['ci', 'setup', '--stack', 'web'], tty, EXIT_SUCCESS, {
            files: { ...files, '/work/.git/config': '' },
        })
        const module = {
            content: 'class Signup: pass\n',
            language: 'python',
            event_count: 1,
            schema_hash: 'abc',
            generator_version: '1',
        }
        for (const flags of [[], ['--check'], ['--dry-run']]) {
            await collect(
                ['stack', 'generate', '--language', 'python', '--out', 'events.py', ...flags],
                tty,
                flags.includes('--check') ? EXIT_CHANGES : EXIT_SUCCESS,
                {
                    files: { ...files, '/work/events.py': 'old\n' },
                    answers: ['no'],
                    respond: () => answer(module),
                }
            )
        }
        await collect(['stack', 'generate', '--language', 'python', '--out', '../events.py'], tty, EXIT_USAGE)
        const binding = { bindings: [{ kind: 'action', key: 'signup', entity_id: '17', status: 'pending' }] }
        await collect(['stack', 'adopt', 'action', 'signup', '17'], tty, EXIT_SUCCESS, {
            respond: () => answer(binding),
        })
        await collect(['stack', 'adopt', 'action', 'missing', '17'], tty, EXIT_USAGE)
        await collect(['push', '--diff', id, '--max-removals', '3'], tty, tty ? EXIT_SUCCESS : EXIT_NEEDS_PERSON, {
            answers: ['no'],
        })
        const reconciled = (url: string): { body: unknown; status: number } =>
            url.endsWith('/reconcile/')
                ? answer({ stack_name: 'web', diff_id: id, acknowledged_warnings: 2 })
                : answer(ready)
        await collect(['stack', 'reconcile', '--diff', id], tty, tty ? EXIT_SUCCESS : EXIT_NEEDS_PERSON, {
            answers: ['yes'],
            respond: reconciled,
        })
        await collect(['stack', 'reconcile', '--diff', id], tty, tty ? EXIT_SUCCESS : EXIT_NEEDS_PERSON, {
            answers: ['no'],
            respond: reconciled,
        })
        const settings = (enabled: boolean) => () => answer({ name: 'web', context_pages_enabled: enabled })
        await collect(['stack', 'context-pages', 'enable', '--yes'], tty, EXIT_SUCCESS, { respond: settings(true) })
        await collect(['stack', 'context-pages', 'enable'], tty, tty ? EXIT_SUCCESS : EXIT_NEEDS_PERSON, {
            answers: ['no'],
        })
        await collect(['stack', 'context-pages', 'disable'], tty, EXIT_SUCCESS, { respond: settings(false) })
        const secret = { name: 'API_TOKEN', updated_at: '2026-11-21T12:00:00Z' }
        await collect(['stack', 'secret', 'set', secret.name, '-'], tty, EXIT_SUCCESS, {
            stdin: 'synthetic input',
            stdinIsTTY: false,
            respond: () => answer(secret),
        })
        await collect(['stack', 'secret', 'list'], tty, EXIT_SUCCESS, { respond: () => answer({ results: [secret] }) })
        await collect(['stack', 'secret', 'remove', secret.name], tty, EXIT_SUCCESS, {
            respond: () => answer(undefined, 204),
        })
        await collect(['diff', '--comment'], tty, EXIT_CHANGES)
        await collect(['diff', '--wait', id, '--raw'], tty, EXIT_CHANGES)
        const previousService = {
            ...report,
            changes: report.changes.map((change) => ({ ...change, summary: untranslated, loses: untranslated })),
            notes: [untranslated],
        }
        for (const flags of [['--raw'], ['--comment']]) {
            await collect(['diff', '--wait', id, ...flags], tty, EXIT_CHANGES, {
                respond: (url, ...rest) =>
                    url.startsWith('https://api.github.com')
                        ? serve(url, ...rest)
                        : answer({ ...ready, diff: previousService }),
            })
        }
        await collect(['push', '--wait', id], tty, EXIT_SUCCESS, {
            respond: () => answer({ ...ready, status: 'pushed' }),
        })
        await collect(
            tty ? ['push'] : ['push', '--diff', id],
            tty,
            tty ? EXIT_SUCCESS : EXIT_PENDING,
            tty ? { answers: ['no'] } : { respond: () => answer(running) }
        )
        await collect(['pull', '--adopt', 'action', '--dry-run'], tty, EXIT_SUCCESS)
        await collect(['pull', '--adopt', 'action', '17', '--dry-run'], tty, EXIT_SUCCESS)
        await collect(['pull', '--adopt', 'action', '17', '--yes'], tty, EXIT_SUCCESS)
        const denied = await collect(['pull', '--adopt', 'action', '17', '--yes'], tty, EXIT_NEEDS_PERSON, {
            respond: (url, ...rest) =>
                url.endsWith('/adopt/')
                    ? answer({ code: 'permission_denied', detail: 'Missing the scope for binding.' }, 403)
                    : serve(url, ...rest),
        })
        expect(denied.stderr).toContain('stack:write')
        expect(denied.stderr).toContain('definitions are on disk')
        const listDenied = await collect(['pull', '--adopt', 'action', '--dry-run'], tty, EXIT_NEEDS_PERSON, {
            respond: () => answer({ code: 'permission_denied', detail: 'Missing the scope for listing.' }, 403),
        })
        expect(listDenied.stderr).toContain('stack:read')
        expect(listDenied.stderr).not.toContain('stack:write')
        await collect(['pull'], tty, EXIT_SUCCESS, { answers: ['no'] })
        await collect(['pull', '--yes'], tty, EXIT_SUCCESS)
        await collect(['pull', '--wait', id, '--dry-run'], tty, EXIT_SUCCESS)
        for (const command of ['diff', 'push', 'pull']) {
            await collect([command, '--wait', id], tty, EXIT_PENDING, { respond: () => answer(running) })
        }
        for (const [status, codes] of Object.entries(codesFromHttp)) {
            for (const code of codes) {
                const exit = forPerson.includes(code) ? EXIT_NEEDS_PERSON : EXIT_FAILURE
                const run = await collect(['push', '--diff', id], tty, exit, {
                    respond: () => answer({ code, detail: untranslated }, Number(status)),
                })
                if (!tty) {
                    expect(run.error().code).toBe(code)
                }
            }
        }
        for (const code of codesFromDiffAndPush) {
            const problem = { code, message: 'Review the named definition.', kind: 'flag', key: 'menu', path: 'name' }
            const saved = {
                ...ready,
                status: 'failed',
                diff: { ...report, errors: [problem, { ...problem, message: untranslated }] },
            }
            const run = await collect(
                ['diff', '--wait', id],
                tty,
                forPerson.includes(code) ? EXIT_NEEDS_PERSON : EXIT_FAILURE,
                { respond: () => answer(saved) }
            )
            if (code === 'secret_literal') {
                expect(run.stderr).not.toContain(problem.message)
                expect(run.stderr).toContain('secret value')
            } else {
                expect(run.stderr).toContain(problem.message)
            }
            if (!tty) {
                expect(run.error().code).toBe(code)
            }
        }
        await collect(['push', '--wait', id], tty, EXIT_FAILURE, {
            respond: () =>
                answer({
                    ...ready,
                    status: 'failed',
                    push_errors: [{ code: 'push_interrupted', message: untranslated }],
                }),
        })
    }
    // `hog ci setup` keeps its --provider option name for existing scripts. Its descriptions say CI service.
    expect(printed.map((text) => text.replaceAll('--provider', '')).filter((text) => forbidden.test(text))).toEqual([])
}, 60_000)
