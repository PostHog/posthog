import { afterAll, describe, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import { evaluateInChild, foldInChild } from '@/stack/child'
import { readJson, runHog } from '@/testing'

import { installStackPackages } from '../../../test/stack-project'

const REPO = resolve(import.meta.dir, '../../../..')
const folders: string[] = []

afterAll(() => {
    for (const folder of folders) {
        rmSync(folder, { recursive: true, force: true })
    }
})

function repository(files: Record<string, string>, compiler = true): string {
    const folder = realpathSync(mkdtempSync(join(tmpdir(), 'hog-stack-')))
    folders.push(folder)
    mkdirSync(join(folder, '.git'))
    mkdirSync(join(folder, 'stacks/web'), { recursive: true })
    writeFileSync(join(folder, 'posthog.json'), JSON.stringify({ stacks: { web: { dir: 'stacks/web' } } }))
    installStackPackages(join(folder, 'stacks/web'), compiler)
    for (const [name, contents] of Object.entries(files)) {
        writeFileSync(join(folder, 'stacks/web', name), contents)
    }
    return folder
}

const PASSING = {
    'index.ts': "export * from './views'\n",
    'views.ts': `import { dashboard, trend } from '@posthog/sdk/define'
export const growth = dashboard('growth', { name: 'Growth', tiles: [trend({ name: 'Signups', series: [{ event: 'signed_up' }] })] })
`,
}

const FAILING = {
    'index.ts': `import { alert, insight, ref } from '@posthog/sdk/define'
export const broken = insight('Broken Key', { query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' } } })
export const orphan = alert('orphan', { insight: ref('insight', 'missing'), subscribed_users: [1], calculation_interval: 'fortnightly' as never, threshold: { configuration: { type: 'absolute', bounds: { upper: 1 } } } })
`,
}

describe('hog check', () => {
    test('a passing stack reports its definitions to a person', async () => {
        const cwd = repository(PASSING)
        const run = await runHog(['check'], { cwd, useDisk: true, stdoutIsTTY: true, env: { NO_COLOR: '1' } })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.stdout.split('\n')[0]).toBe('✓ Stack web passed check: 1 dashboard, 1 insight')
        expect(run.stdout).toContain('Types checked with TypeScript')
    }, 30_000)

    test('a passing stack gives agents the summary and --raw the description', async () => {
        const repo = repository(PASSING)
        const cwd = join(repo, 'stacks')
        writeFileSync(join(cwd, 'posthog.json'), JSON.stringify({ stacks: { web: { dir: 'web' } } }))
        const agent = await runHog(['stack', 'check'], { cwd, useDisk: true })
        expect(agent.exitCode).toBe(EXIT_SUCCESS)
        expect(agent.json()).toEqual({
            ok: true,
            problems: [],
            counts: { dashboard: 1, insight: 1 },
            output: { stdout: '', stderr: '' },
            dir: 'web',
            stack: 'web',
            typeCheck: { status: 'passed', compiler: expect.any(String), config: 'stacks/web/tsconfig.json' },
        })
        const raw = await runHog(['check', '--raw'], { cwd, useDisk: true })
        const { description } = readJson(raw.stdout) as { description: { resources: { kind: string; key: string }[] } }
        expect(description.resources.map(({ kind, key }) => `${kind}:${key}`)).toEqual([
            'dashboard:growth',
            'insight:growth-signups',
        ])
        expect(description.resources[0]).toMatchObject({ source: { file: 'stacks/web/views.ts' } })
    }, 30_000)

    test('a failing stack lists every problem and exits with 1', async () => {
        const cwd = repository(FAILING)
        const human = await runHog(['check'], {
            cwd,
            useDisk: true,
            stdoutIsTTY: true,
            env: { NO_COLOR: '1' },
        })
        expect(human.exitCode).toBe(EXIT_FAILURE)
        expect(human.stdout.split('\n').slice(0, 4)).toEqual([
            '✗ Stack web failed check: 3 problems',
            expect.stringContaining('stacks/web/index.ts  alert orphan  calculation_interval:'),
            '  error  stacks/web/index.ts  alert orphan  insight refers to the insight "missing", which this stack doesn\'t define. Export it from the stack\'s index.ts, or fix the key.',
            '  error  stacks/web/index.ts  insight Broken Key  The insight key "Broken Key" can only use lowercase letters, digits, "_" and "-", starting with a letter or digit.',
        ])

        const agent = await runHog(['check'], { cwd, useDisk: true })
        expect(agent.exitCode).toBe(EXIT_FAILURE)
        const { ok, problems } = agent.json() as {
            ok: boolean
            problems: { code: string; key: string; path?: string }[]
        }
        expect(ok).toBe(false)
        expect(problems.map(({ code, key, path }) => [code, key, path])).toEqual([
            ['schema_invalid', 'orphan', 'calculation_interval'],
            ['reference_missing', 'orphan', 'insight'],
            ['key_invalid', 'Broken Key', undefined],
        ])
    }, 30_000)

    test('the folder prints into its own streams and each check rereads its imports', async () => {
        const cwd = repository({ ...PASSING, 'noise.ts': "console.log('first load'); console.error('a warning')" })
        writeFileSync(join(cwd, 'stacks/web/index.ts'), "import './noise'; export * from './views'")
        const agent = await runHog(['check', '--raw'], { cwd, useDisk: true })
        expect(agent.exitCode).toBe(EXIT_SUCCESS)
        expect(agent.json()).toMatchObject({ output: { stdout: 'first load\n', stderr: 'a warning\n' } })
        expect(agent.stdout.trim().split('\n')).toHaveLength(1)
        expect(agent.stderr).toBe('')

        writeFileSync(join(cwd, 'stacks/web/noise.ts'), "console.log('second load')")
        const human = await runHog(['check', '-o', 'text'], { cwd, useDisk: true })
        expect(human.stdout).toContain('Captured stdout: second load')
        expect(human.stdout).not.toContain('first load')
    }, 30_000)

    test('a definition that leaves a timer running still returns its result', async () => {
        const cwd = repository({ ...PASSING, 'timer.ts': 'setInterval(() => {}, 1000)' })
        writeFileSync(join(cwd, 'stacks/web/index.ts'), "import './timer'; export * from './views'")
        const run = await runHog(['check', '-o', 'json'], {
            cwd,
            useDisk: true,
            evaluateStack: (folder, root) => evaluateInChild(folder, root, true, 15_000),
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
    }, 30_000)

    test('a message a definition sends itself cannot replace the result', async () => {
        const forged = { description: { version: 1, resources: [] }, problems: [], typeCheck: { status: 'passed' } }
        const cwd = repository({ ...PASSING, 'forge.ts': `// @ts-nocheck\nprocess.send?.(${JSON.stringify(forged)})` })
        writeFileSync(join(cwd, 'stacks/web/index.ts'), "import './forge'; export * from './views'")
        const run = await runHog(['check', '-o', 'json'], { cwd, useDisk: true })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.json()).toMatchObject({ counts: { dashboard: 1, insight: 1 } })
    }, 30_000)

    test.skipIf(process.platform === 'win32')(
        'a process a definition starts cannot hold the check open or outlive it',
        async () => {
            const cwd = repository(PASSING)
            const pidFile = join(cwd, 'sleeper.pid')
            writeFileSync(
                join(cwd, 'stacks/web/sleeper.ts'),
                [
                    '// @ts-nocheck',
                    "import { spawn } from 'node:child_process'",
                    "import { writeFileSync } from 'node:fs'",
                    "const sleeper = spawn('/bin/sleep', ['60'], { stdio: 'inherit' })",
                    `writeFileSync(${JSON.stringify(pidFile)}, String(sleeper.pid))`,
                ].join('\n')
            )
            writeFileSync(join(cwd, 'stacks/web/index.ts'), "import './sleeper'; export * from './views'")
            const run = await runHog(['check', '-o', 'json'], {
                cwd,
                useDisk: true,
                evaluateStack: (folder, root) => evaluateInChild(folder, root, true, 15_000),
            })
            expect(run.exitCode).toBe(EXIT_SUCCESS)
            const pid = Number(readFileSync(pidFile, 'utf8'))
            const alive = (): boolean => {
                try {
                    process.kill(pid, 0)
                    return true
                } catch {
                    return false
                }
            }
            // The orphaned process is reaped by the system after the kill, which takes a moment.
            for (let tries = 0; alive() && tries < 40; tries++) {
                await Bun.sleep(50)
            }
            expect(alive()).toBe(false)
        },
        30_000
    )

    test('a definition that never finishes gives an actionable timeout', async () => {
        const cwd = repository({ 'index.ts': 'while (true) {}' }, false)
        const run = await runHog(['check'], {
            cwd,
            useDisk: true,
            evaluateStack: (folder, root) => evaluateInChild(folder, root, true, 1000),
        })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.error()).toMatchObject({ code: 'stack_evaluation_timeout', hint: expect.stringContaining('loop') })
    })

    test('pull captures folder output while folding a literal and returning a computed field for review', async () => {
        const repo = repository({
            'index.ts': [
                "import { dashboard } from '@posthog/sdk/define'",
                "console.log('Reading the dashboard')",
                "console.error('Dashboard note')",
                "const label = ['Web', 'overview'].join(' ')",
                "export const overview = dashboard('overview', { name: label, description: 'Earlier', tiles: [] })",
            ].join('\n'),
        })
        const dir = join(repo, 'stacks/web')
        const changed = 'A longer description. '.repeat(8192)
        const original = readFileSync(join(dir, 'index.ts'), 'utf8')
        const result = await foldInChild(
            dir,
            [
                {
                    kind: 'dashboard',
                    key: 'overview',
                    fields: [
                        { path: 'description', pushed: 'Earlier', found: changed },
                        { path: 'name', pushed: 'Web overview', found: 'Web dashboard' },
                    ],
                },
            ],
            true,
            { root: repo, targets: [join(dir, 'index.ts')] }
        )
        expect(result.output).toEqual({ stdout: 'Reading the dashboard\n', stderr: 'Dashboard note\n' })
        expect(result.applied).toEqual([
            {
                kind: 'dashboard',
                key: 'overview',
                file: 'stacks/web/index.ts',
                path: 'description',
                before: 'Earlier',
                after: changed,
            },
        ])
        expect(result.manual).toMatchObject([
            {
                kind: 'dashboard',
                key: 'overview',
                file: 'stacks/web/index.ts',
                path: 'name',
                pushed: 'Web overview',
                found: 'Web dashboard',
            },
        ])
        expect(readFileSync(join(dir, 'index.ts'), 'utf8')).toBe(original)
        expect(result.edits).toHaveLength(1)
        expect(result.edits[0]!.before).toBe(original)
        expect(result.edits[0]!.after).toContain(`description: '${changed}'`)
        expect(result.edits[0]!.after).toContain('name: label')
    }, 30_000)

    const environments = {
        dev: { host: 'https://us.posthog.com', project: 2 },
        prod: { host: 'https://us.posthog.com', project: 3 },
    }
    const files = {
        '/work/posthog.json': JSON.stringify({ stacks: { web: { dir: 'web', environments } } }),
        '/work/web/index.ts': 'export {}',
    }

    test.each([
        { argv: ['--stack', 'constructor'], code: 'stack_unknown' },
        { argv: ['--stack', 'Web'], code: 'invalid_input' },
        { argv: [], code: 'environment_required' },
        { argv: ['--env', 'constructor'], code: 'environment_unknown' },
        { argv: ['--env', 'unknown'], code: 'environment_unknown' },
    ])('stack selection: $argv returns $code', async ({ argv, code }) => {
        const run = await runHog(['check', ...argv], { files })
        expect(run.exitCode).toBe(EXIT_USAGE)
        expect(run.error()).toMatchObject({ code, hint: expect.any(String) })
    })

    test.each([{ argv: ['check'] }, { argv: ['stack', 'check'] }])(
        '$argv sends no requests even when an update check is due',
        async ({ argv }) => {
            const run = await runHog([...argv, '--env', 'prod'], {
                files,
                evaluateStack: async () => ({
                    description: { version: 1, resources: [] },
                    typeCheck: { status: 'passed' },
                    problems: [],
                    output: { stdout: '', stderr: '' },
                }),
                telemetryToken: 'test',
                build: { version: '1.0.0', date: '2025-01-01' },
            })
            expect(run.exitCode).toBe(EXIT_SUCCESS)
            expect(run.json()).toMatchObject({ env: 'prod' })
            expect(run.requests).toEqual([])
        }
    )

    test.each(['missing', 'broken'])('a %s compiler cannot produce a successful check', async (compiler) => {
        const cwd = repository(PASSING, false)
        if (compiler === 'broken') {
            const dependency = join(cwd, 'stacks/web/node_modules/typescript')
            mkdirSync(dependency)
            writeFileSync(join(dependency, 'index.js'), 'module.exports = {}')
        }
        const run = await runHog(['check'], { cwd, useDisk: true })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        const reason =
            'This project has no usable TypeScript compiler. Add typescript as a dev dependency to check types.'
        expect(run.json()).toMatchObject({
            ok: false,
            typeCheck: { status: 'skipped', reason },
            problems: [{ code: 'type_check_skipped', severity: 'error', message: reason }],
        })
        if (compiler === 'missing') {
            const human = await runHog(['check', '-o', 'text'], { cwd, useDisk: true })
            expect(human.stdout).toContain('failed check: 1 problem')
            expect(human.stdout).toContain(reason)
        }
    })

    test('an import through tsconfig paths is reported with the repository-relative source and line', async () => {
        const repo = repository({ ...PASSING, 'index.ts': "export * from '@views'\n" })
        const dir = join(repo, 'stacks/web')
        const config = readJson(readFileSync(join(dir, 'tsconfig.json'), 'utf8')) as { compilerOptions: object }
        writeFileSync(
            join(dir, 'tsconfig.json'),
            JSON.stringify({
                compilerOptions: { ...config.compilerOptions, paths: { '@views': ['./views.ts'] } },
            })
        )
        const run = await runHog(['check'], { cwd: dir, useDisk: true })
        expect(run.exitCode).toBe(EXIT_FAILURE)
        expect(run.json()).toMatchObject({
            typeCheck: { status: 'failed' },
            problems: expect.arrayContaining([
                expect.objectContaining({ code: 'import_unsupported', file: 'stacks/web/index.ts', line: 1 }),
            ]),
        })
    }, 30_000)

    test("the slo-monitoring port's description.json is what check evaluates the folder into", async () => {
        const run = await runHog(['check', '--raw', '--stack', 'slo-monitoring'], {
            cwd: REPO,
            useDisk: true,
        })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        const { description, problems } = readJson(run.stdout) as { description: unknown; problems: { code: string }[] }
        // The port keeps the grid fields of its HCL layouts, which check warns PostHog drops.
        expect(problems.filter((problem) => problem.code !== 'layout_field_dropped')).toEqual([])
        const committed = readJson(readFileSync(join(REPO, '.ph/us/project-2/slo-monitoring/description.json'), 'utf8'))
        expect(description).toEqual(committed)
    }, 30_000)
})
