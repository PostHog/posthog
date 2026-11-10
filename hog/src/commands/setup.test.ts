import { describe, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import type { LearnResult, SkillsLibrary, SkillsResult } from '@posthog/mcp/src/cli/library-types'

import { escapeControls } from '@/core/output'
import { processRuntime } from '@/core/runtime'
import { LOGIN_SCOPES } from '@/posthog/device-auth'
import { AGENTS_FILE, writeBlock } from '@/setup/agents-md'
import { fakeRuntime, readJson, runHog, type HogRun } from '@/testing'

const EU = 'https://eu.posthog.com'
const TELEMETRY = 'https://us.i.posthog.com/batch/'
const START = Date.UTC(2026, 0, 1)
const AGENT = { CLAUDECODE: '1' }
const TOKEN = 'phc_example_project_token'

function statePath(folder: string): string {
    return `/home/test/.posthog/setup/${createHash('sha256').update(folder).digest('hex')}.json`
}

function ok<T>(value: T): SkillsResult<T> {
    return { ok: true, value }
}

function fakeSkills(installs: string[]): () => SkillsLibrary {
    return () => ({
        learn: async ({ skill = '', paths, lines }) => {
            const [path = 'SKILL.md'] = paths
            return ok<LearnResult>({
                output: { kind: 'text', text: `${skill} ${path}` },
                reads: [
                    {
                        source: 'posthog',
                        skill: skill.replace('posthog:', ''),
                        path,
                        readKind: lines === undefined ? 'file' : 'file_lines',
                    },
                ],
                assets: [],
            })
        },
        instrumentSkills: async () =>
            ok({
                skills: [
                    'posthog:instrument-integration',
                    'posthog:instrument-feature-flags',
                    'posthog:instrument-metrics',
                ],
                assets: [],
            }),
        installable: async () =>
            ok({
                skills: [
                    {
                        id: 'querying-posthog-data',
                        name: 'Querying PostHog data',
                        description: 'Write HogQL',
                        tags: [],
                    },
                ],
                assets: [],
            }),
        install: async (id, { cwd }) => {
            installs.push(`${cwd}:${id}`)
            return ok({ skill: { id, directory: `${cwd}/.agents/skills/${id}`, fileCount: 1 }, assets: [] })
        },
    })
}

interface World {
    run(argv: string[], extra?: { cwd?: string; telemetry?: boolean; person?: string[] }): Promise<HogRun>
    files: Record<string, string>
    // When PostHog received each event, as epoch milliseconds.
    events: number[]
    installs: string[]
    intentStatus: number
    token: string
}

// One machine across several hog runs: files and the keychain carry over, and PostHog answers the
// device login, the project, product intents and event counts.
function world(files: Record<string, string> = {}, cwd = '/work'): World {
    let keychain: Record<string, string> = {}
    const state: World = {
        files,
        events: [],
        installs: [],
        intentStatus: 201,
        token: TOKEN,
        async run(argv, extra = {}) {
            const respond = (url: string, body: unknown): { status: number; body: unknown } => {
                const origin = new URL(url).origin
                if (url === TELEMETRY) {
                    return { status: 200, body: {} }
                }
                if (url.endsWith('/oauth/device-authorization/')) {
                    return {
                        status: 200,
                        body: {
                            device_code: 'device-secret',
                            user_code: 'BCDF-GHJK',
                            verification_uri: `${origin}/device`,
                            verification_uri_complete: `${origin}/device?code=BCDF-GHJK`,
                            expires_in: 1800,
                            interval: 5,
                        },
                    }
                }
                if (url.endsWith('/oauth/token/')) {
                    return {
                        status: 200,
                        body: {
                            access_token: `pha_${'a'.repeat(43)}`,
                            token_type: 'Bearer',
                            expires_in: 604800,
                            refresh_token: `phr_${'r'.repeat(43)}`,
                            scope: LOGIN_SCOPES.join(' '),
                            scoped_teams: [42],
                            scoped_organizations: [],
                        },
                    }
                }
                if (url.endsWith('/api/environments/42/add_product_intent/')) {
                    return { status: state.intentStatus, body: { detail: 'Intent refused.' } }
                }
                if (url.endsWith('/api/environments/42/') || url.endsWith('/api/projects/42/')) {
                    return {
                        status: 200,
                        body: { api_token: state.token, uuid: 'project-uuid', organization: 'org-1' },
                    }
                }
                if (url.endsWith('/api/users/@me/')) {
                    return { status: 200, body: { distinct_id: 'user-1' } }
                }
                if (url.endsWith('/api/environments/42/query')) {
                    const query = (body as { query: { query: string } }).query.query
                    const since = Date.parse(/created_at >= toDateTime\('([^']+)'\)/.exec(query)?.[1] ?? '')
                    return { status: 200, body: { results: [[state.events.filter((at) => at >= since).length]] } }
                }
                return { status: 404, body: { detail: 'Not found.' } }
            }
            const result = await runHog(argv, {
                env: extra.person ? { NO_COLOR: '1' } : AGENT,
                stdoutIsTTY: extra.person !== undefined,
                answers: extra.person,
                cwd: extra.cwd ?? cwd,
                files: state.files,
                keychain,
                respond,
                skills: fakeSkills(state.installs),
                telemetryToken: extra.telemetry ? 'phc_telemetry' : undefined,
            })
            state.files = result.files
            keychain = result.keychain
            return result
        },
    }
    return state
}

const ANSWERS = ['--reason', 'See where users drop off', '--products', 'session-replay,feature-flags', '--region', 'eu']

function telemetryEvents(
    result: HogRun
): { event: string; distinct_id: string; properties: Record<string, unknown> }[] {
    return result.requests.filter((request) => request.url === TELEMETRY).flatMap((request: any) => request.body.batch)
}

describe('hog setup', () => {
    test('an agent goes from a fresh folder to connected, one hand-off at a time', async () => {
        const machine = world({ '/work/AGENTS.md': '# My app\n\nUse pnpm.\n' })

        const fresh = await machine.run(['setup'])
        expect(fresh.json()).toMatchObject({
            step: 'purpose',
            status: 'in_progress',
            code: 'setup_needs_answers',
            done: [],
            next: { kind: 'ask_user', command: expect.stringContaining('--reason') },
            context: { folder: '/work', configPath: null },
        })
        const questions = (fresh.json() as any).next.ask
        expect(questions.map((question: { id: string }) => question.id)).toEqual(['reason', 'products', 'region'])
        expect(questions[1].choices.map((choice: { value: string }) => choice.value)).toContain('metrics')

        const started = await machine.run(['setup', 'next', ...ANSWERS], { telemetry: true })
        expect(started.json()).toMatchObject({
            step: 'login',
            code: 'setup_login_pending',
            next: { kind: 'wait', command: 'hog setup next', url: `${EU}/device?code=BCDF-GHJK`, code: 'BCDF-GHJK' },
        })
        expect(started.stdout).not.toContain('device-secret')
        expect(telemetryEvents(started).find((event) => event.event === 'hog setup started')?.properties).toMatchObject(
            {
                reason: 'See where users drop off',
                products: ['session-replay', 'feature-flags'],
                region: 'eu',
            }
        )

        const loggedIn = await machine.run(['setup', 'next'], { telemetry: true })
        expect(loggedIn.json()).toMatchObject({
            step: 'install',
            code: 'setup_skill_not_read',
            done: [{ step: 'purpose' }, { step: 'login' }, { step: 'project' }, { step: 'agents-md' }],
            next: {
                kind: 'read',
                read: [
                    'hog learn posthog:instrument-integration',
                    'hog learn posthog:instrument-integration references/COMMANDMENTS.md',
                ],
            },
            context: { host: EU, projectId: '42', region: 'eu', token: TOKEN, apiHost: 'https://eu.i.posthog.com' },
        })
        expect(readJson(machine.files['/work/posthog.json'] ?? '')).toMatchObject({ host: EU, projectId: 42 })
        expect(machine.files['/work/AGENTS.md']).toStartWith('# My app\n\nUse pnpm.\n\n<!-- posthog:setup:start -->')
        expect(machine.files['/work/AGENTS.md']).toContain('PostHog setup is in progress')
        expect(
            loggedIn.requests.filter((request) => request.url.endsWith('/add_product_intent/')).map((r) => r.body)
        ).toEqual([
            { product_type: 'session_replay', metadata: { source: 'hog setup' } },
            { product_type: 'feature_flags', metadata: { source: 'hog setup' } },
        ])
        const installId = machine.files['/home/test/.posthog/hog-telemetry-id']?.trim()
        expect(telemetryEvents(loggedIn)[0]).toMatchObject({
            event: '$identify',
            distinct_id: 'user-1',
            properties: { $anon_distinct_id: installId },
        })

        await machine.run(['learn', 'posthog:instrument-integration'])
        await machine.run(['learn', 'posthog:instrument-integration', 'references/COMMANDMENTS.md', '--lines', '1:5'])
        const halfRead = await machine.run(['setup', 'next'])
        expect(halfRead.json()).toMatchObject({ step: 'install', code: 'setup_skill_not_read' })

        await machine.run(['learn', 'posthog:instrument-integration', 'references/COMMANDMENTS.md'])
        const installed = await machine.run(['setup', 'next'])
        expect(installed.json()).toMatchObject({
            step: 'review',
            code: 'setup_not_reviewed',
            next: { kind: 'read', command: 'hog setup next --reviewed' },
        })

        const notReviewed = await machine.run(['setup', 'next'])
        expect(notReviewed.json()).toMatchObject({ step: 'review', code: 'setup_not_reviewed' })

        // An event PostHog received before the setup started doesn't count.
        machine.events.push(START - 60_000)
        const reviewed = await machine.run(['setup', 'next', '--reviewed'])
        expect(reviewed.exitCode).toBe(1)
        expect(reviewed.json()).toMatchObject({
            step: 'verify',
            code: 'setup_no_events_yet',
            next: { kind: 'run', command: 'hog setup next' },
            context: { events: { since: '2026-01-01T00:00:00.000Z', count: 0 } },
        })

        machine.events.push(START + 60_000)
        const verified = await machine.run(['setup', 'next'])
        expect(verified.exitCode).toBe(0)
        expect(verified.json()).toMatchObject({
            step: 'products',
            next: { kind: 'ask_user', ask: [{ id: 'skills', option: '--install-skills' }] },
        })
        expect((verified.json() as any).context.products.slice(0, 2)).toMatchObject([
            { id: 'session-replay', chosen: true, command: 'hog learn -s "session replay"' },
            { id: 'feature-flags', chosen: true, command: 'hog learn posthog:instrument-feature-flags' },
        ])

        const finished = await machine.run(['setup', 'next', '--install-skills', 'querying-posthog-data'])
        expect(finished.json()).toMatchObject({ step: 'connected', status: 'connected', next: { kind: 'done' } })
        expect(machine.installs).toEqual(['/work:querying-posthog-data'])
        const agentsMd = machine.files['/work/AGENTS.md'] ?? ''
        expect(agentsMd).toStartWith('# My app\n\nUse pnpm.\n\n<!-- posthog:setup:start -->')
        expect(agentsMd).not.toContain('in progress')
        expect(agentsMd).toContain(`project 42 on ${EU}`)
        expect(agentsMd.indexOf('Session replay')).toBeLessThan(agentsMd.indexOf('Debugging errors'))

        const summary = await machine.run(['setup'])
        expect(summary.json()).toMatchObject({
            status: 'connected',
            context: { loggedIn: true, events: { count: 1 } },
        })

        const day = 24 * 60 * 60 * 1000
        const state = readJson(machine.files[statePath('/work')] ?? '{}') as object
        machine.files[statePath('/work')] = JSON.stringify({ ...state, startedAt: START - 30 * day })
        machine.events.push(START - 10 * day)
        const weeksLater = await machine.run(['setup'])
        expect(weeksLater.json()).toMatchObject({
            context: { events: { since: new Date(START - day).toISOString(), count: 2 } },
        })
    })

    test('a person answers the questions and approves the login at the terminal', async () => {
        const machine = world()
        machine.token = 'phc_custom\u001b]52;c;aGk=\u0007'

        const result = await machine.run(['setup', 'next'], { person: ['Track signups', 'product-analytics', 'us'] })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain('Done  Interested in Product analytics')
        expect(result.stdout).toContain('Done  Logged in to https://us.posthog.com, project 42')
        expect(result.stdout).toContain(`Project token: ${escapeControls(machine.token)}`)
        expect(result.stdout).not.toContain('\u001b')
        expect(result.stdout).toContain('Next: Run both commands')
    })

    test('a person who names the skills at the terminal gets them without a prompt', async () => {
        const machine = world()
        await machine.run(['setup', 'next', ...ANSWERS])
        await machine.run(['setup', 'next'])
        await machine.run(['learn', 'posthog:instrument-integration'])
        await machine.run(['learn', 'posthog:instrument-integration', 'references/COMMANDMENTS.md'])
        machine.events.push(START + 60_000)
        await machine.run(['setup', 'next'])
        const products = await machine.run(['setup', 'next', '--reviewed'])
        expect(products.json()).toMatchObject({ step: 'products' })

        const finished = await machine.run(['setup', 'next', '--install-skills', 'querying-posthog-data'], {
            person: [],
        })

        expect(finished.exitCode).toBe(0)
        expect(machine.installs).toEqual(['/work:querying-posthog-data'])
    })

    test('a clone without the state file starts over at the first step hog can not prove', async () => {
        const machine = world()
        await machine.run(['setup', 'next', ...ANSWERS])
        await machine.run(['setup', 'next'])
        delete machine.files[statePath('/work')]
        machine.intentStatus = 500

        const status = await machine.run(['setup'])
        expect(status.json()).toMatchObject({ step: 'purpose' })
        expect((status.json() as any).next.ask.map((question: { id: string }) => question.id)).toEqual([
            'reason',
            'products',
        ])

        const resumed = await machine.run(['setup', 'next', '--reason', 'Again', '--products', 'session-replay'])
        expect(resumed.json()).toMatchObject({
            step: 'install',
            done: [{ step: 'purpose' }, { step: 'login' }, { step: 'project' }, { step: 'agents-md' }],
            context: { warnings: [expect.stringContaining("PostHog didn't record your interest in Session replay")] },
        })
        expect(resumed.requests.some((request) => request.url.endsWith('/oauth/device-authorization/'))).toBe(false)
    })

    test('a clone of a connected folder shows the summary and asks a new teammate to log in', async () => {
        const machine = world({
            '/work/posthog.json': JSON.stringify({ host: EU, projectId: 42 }),
            '/work/AGENTS.md':
                '<!-- posthog:setup:start -->\nThis folder sends data to PostHog project 42.\n<!-- posthog:setup:end -->\n',
        })

        const result = await machine.run(['setup'])

        expect(result.json()).toMatchObject({
            status: 'connected',
            context: { loggedIn: false },
            next: { kind: 'run', command: 'hog auth login' },
        })
    })

    test('each app in a monorepo keeps its own setup, from its own posthog.json', async () => {
        const machine = world({
            '/repo/.git/HEAD': 'ref: refs/heads/main\n',
            '/repo/apps/web/posthog.json': JSON.stringify({ host: EU }),
            '/repo/apps/api/posthog.json': JSON.stringify({ host: EU }),
        })

        const web = await machine.run(['setup', 'next', '--reason', 'Web', '--products', 'none'], {
            cwd: '/repo/apps/web/src',
        })
        const api = await machine.run(['setup'], { cwd: '/repo/apps/api' })

        expect(web.json()).toMatchObject({ step: 'login', context: { folder: '/repo/apps/web' } })
        expect(api.json()).toMatchObject({ step: 'purpose', context: { folder: '/repo/apps/api' } })
        expect(machine.files[statePath('/repo/apps/web')]).toBeDefined()
    })

    test('a setup in another folder starts its own login instead of waiting for this one', async () => {
        const machine = world({
            '/repo/.git/HEAD': 'ref: refs/heads/main\n',
            '/repo/apps/web/posthog.json': JSON.stringify({ host: EU }),
            '/repo/apps/api/posthog.json': JSON.stringify({ host: EU }),
        })

        const web = await machine.run(['setup', 'next', '--reason', 'Web', '--products', 'none'], {
            cwd: '/repo/apps/web',
        })
        const api = await machine.run(['setup', 'next', '--reason', 'Api', '--products', 'none'], {
            cwd: '/repo/apps/api',
        })

        expect(web.json()).toMatchObject({ code: 'setup_login_pending' })
        expect(api.json()).toMatchObject({ code: 'setup_login_pending' })
        expect(api.requests.filter((request) => request.url.endsWith('/oauth/device-authorization/'))).toHaveLength(1)
    })

    test('a login approved in the last seconds before it expires still finishes', async () => {
        const machine = world()
        await machine.run(['setup', 'next', ...ANSWERS])
        const pendingFile = Object.keys(machine.files).find((path) => path.includes('/pending-setup-next')) ?? ''
        machine.files[pendingFile] = JSON.stringify({
            ...(readJson(machine.files[pendingFile] ?? '{}') as object),
            expiresAt: START + 10_000,
        })

        const resumed = await machine.run(['setup', 'next'])

        expect(resumed.requests.filter((request) => request.url.endsWith('/oauth/device-authorization/'))).toEqual([])
        expect(resumed.json()).toMatchObject({ step: 'install' })
    })

    test('a login started with --host resumes there without --host', async () => {
        const machine = world()
        const host = 'https://ph.example.com'

        const started = await machine.run(['setup', 'next', '--host', host, '--reason', 'x', '--products', 'none'])
        const resumed = await machine.run(['setup', 'next'])

        expect(started.json()).toMatchObject({ next: { kind: 'wait', url: `${host}/device?code=BCDF-GHJK` } })
        expect(resumed.requests.filter((request) => request.url.endsWith('/oauth/device-authorization/'))).toEqual([])
        expect(resumed.json()).toMatchObject({ step: 'install', context: { host, projectId: '42' } })
    })

    test('a login to another project than posthog.json names leaves posthog.json alone', async () => {
        const config = JSON.stringify({ host: EU, projectId: 7 })
        const machine = world({ '/work/posthog.json': config })

        const started = await machine.run(['setup', 'next', '--reason', 'x', '--products', 'none'])
        const approved = await machine.run(['setup', 'next'])

        expect((started.json() as any).next.instructions).toContain('picking project 7')
        expect(approved.error()).toMatchObject({ code: 'setup_project_mismatch' })
        expect(machine.files['/work/posthog.json']).toBe(config)
    })

    test.each([
        ['some answers without the rest', ['setup', 'next', '--reason', 'x'], 'setup_needs_answers'],
        [
            'a product hog does not know',
            ['setup', 'next', ...ANSWERS.slice(0, 2), '--products', 'nope', '--region', 'us'],
            'setup_unknown_product',
        ],
        ['answers without next', ['setup', '--reason', 'x'], 'setup_options_need_next'],
        ['an action other than next', ['setup', 'go'], 'invalid_setup_command'],
    ])('%s fails with a hint', async (_name, argv, code) => {
        const result = await world().run(argv)

        expect(result.exitCode).toBe(2)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })

    test('hog learn records nothing without a setup in the folder', async () => {
        const machine = world()

        const result = await machine.run(['learn', 'posthog:instrument-integration'])

        expect(result.exitCode).toBe(0)
        expect(Object.keys(machine.files).filter((path) => path.includes('/setup/'))).toEqual([])
    })
})

describe('the AGENTS.md block', () => {
    const block = (body: string): string => `<!-- posthog:setup:start -->\n${body}\n<!-- posthog:setup:end -->`

    test.each([
        [
            'replaces the block in place and keeps the rest',
            { [`/app/${AGENTS_FILE}`]: `# App\n\n${block('old')}\n\n## Tests\n` },
            { [`/app/${AGENTS_FILE}`]: `# App\n\n${block('new')}\n\n## Tests\n` },
        ],
        [
            'writes CLAUDE.md too when it does not import AGENTS.md',
            { '/app/CLAUDE.md': '# Claude\n' },
            { [`/app/${AGENTS_FILE}`]: `${block('new')}\n`, '/app/CLAUDE.md': `# Claude\n\n${block('new')}\n` },
        ],
        [
            'leaves a CLAUDE.md that imports AGENTS.md inside a sentence alone',
            { '/app/CLAUDE.md': 'Read @AGENTS.md first.\n' },
            { [`/app/${AGENTS_FILE}`]: `${block('new')}\n`, '/app/CLAUDE.md': 'Read @AGENTS.md first.\n' },
        ],
        [
            'updates a block left in a CLAUDE.md that now imports AGENTS.md',
            { '/app/CLAUDE.md': `@AGENTS.md\n\n${block('old')}\n` },
            { [`/app/${AGENTS_FILE}`]: `${block('new')}\n`, '/app/CLAUDE.md': `@AGENTS.md\n\n${block('new')}\n` },
        ],
        [
            'leaves a CLAUDE.md that imports AGENTS.md alone',
            { '/app/CLAUDE.md': '@AGENTS.md\n' },
            { [`/app/${AGENTS_FILE}`]: `${block('new')}\n`, '/app/CLAUDE.md': '@AGENTS.md\n' },
        ],
    ])('%s', async (_name, files, expected) => {
        const runtime = fakeRuntime({ files })

        await writeBlock(runtime, '/app', 'new')

        expect(runtime.files).toEqual(expected)
    })

    function linkedFolder(): { root: string; folder: string } {
        const root = mkdtempSync(join(tmpdir(), 'hog-agents-md-'))
        const folder = join(root, 'app')
        mkdirSync(folder)
        writeFileSync(join(root, 'outside.md'), '# Outside\n')
        return { root, folder }
    }

    test.each([
        ['an AGENTS.md that links outside the folder', AGENTS_FILE, '../outside.md'],
        ['a CLAUDE.md that links outside the folder', 'CLAUDE.md', '../outside.md'],
        ['an AGENTS.md that links to a missing file outside the folder', AGENTS_FILE, '../missing.md'],
    ])('%s is refused, and nothing outside it changes', async (_name, file, target) => {
        const { root, folder } = linkedFolder()
        symlinkSync(target, join(folder, file))

        await expect(writeBlock(processRuntime(), folder, 'new')).rejects.toMatchObject({
            code: 'setup_file_outside_folder',
        })

        expect(readFileSync(join(root, 'outside.md'), 'utf8')).toBe('# Outside\n')
        expect(existsSync(join(root, 'missing.md'))).toBe(false)
        expect(existsSync(join(folder, file === AGENTS_FILE ? 'CLAUDE.md' : AGENTS_FILE))).toBe(false)
    })

    test('a CLAUDE.md linked to AGENTS.md inside the folder stays a link', async () => {
        const { folder } = linkedFolder()
        writeFileSync(join(folder, AGENTS_FILE), '# App\n')
        symlinkSync(AGENTS_FILE, join(folder, 'CLAUDE.md'))

        const written = await writeBlock(processRuntime(), folder, 'new')

        expect(written.map((file) => file.status)).toEqual(['updated', 'unchanged'])
        expect(lstatSync(join(folder, 'CLAUDE.md')).isSymbolicLink()).toBe(true)
        expect(readFileSync(join(folder, AGENTS_FILE), 'utf8')).toBe(`# App\n\n${block('new')}\n`)
    })

    test('a file with only one marker fails instead of growing a second block', async () => {
        const runtime = fakeRuntime({ files: { [`/app/${AGENTS_FILE}`]: '<!-- posthog:setup:start -->\nleft over\n' } })

        await expect(writeBlock(runtime, '/app', 'new')).rejects.toMatchObject({ code: 'setup_block_broken' })
    })
})
