import childProcess, { ChildProcess, SpawnOptions, spawn } from 'child_process'
import { once } from 'events'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import http from 'http'
import net from 'net'
import os from 'os'
import path from 'path'
import { promisify } from 'util'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'
import { isPortFree } from '~/tests/helpers/service-process'

import { CdpRole } from '../cards'
import { Environment, createEnvironment } from './environment'
import * as processes from './processes'
import { ProcEntry, holdRunLock, lockAddress, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ROLE_PORTS, Role, roleSpecs, secretsOf } from './roles'
import { STACK, eventsConsumerGroup, membersOf, pingRedis, withPostgres } from './stack'

const SELF = 100
const REPO = '/work/posthog'
const NODEJS = `${REPO}/nodejs`
const MARKED_ENV = ['PATH=/usr/bin', 'SCENARIO_RUNNER=1']
const PLAIN_ENV = ['PATH=/usr/bin']
const modeEnv = (mode: string): string[] => [...PLAIN_ENV, `PLUGIN_SERVER_MODE=${mode}`]
const NODEJS_DIR = path.resolve(__dirname, '..', '..', '..')

const proc = (
    pid: number,
    pgid: number,
    cmdline: string,
    environ: string[] | null,
    cwd: string | null = NODEJS
): ProcEntry => ({
    pid,
    pgid,
    cmdline,
    cwd,
    environ,
})

const runner = proc(SELF, SELF, 'node scenarios run smoke', PLAIN_ENV)

const inSchema = (url: string, schema: string): string =>
    `${url}${url.includes('?') ? '&' : '?'}options=${encodeURIComponent(`-c search_path=${schema}`)}`

const writeFake = (file: string, body: string): void => {
    writeFileSync(file, `#!${process.execPath}\n${body}`, { mode: 0o755 })
}

describe('scenario environment', () => {
    describe('planCleanup', () => {
        it.each<[string, ProcEntry[], { groups: number[]; pids: number[]; strangers: number[] }]>([
            [
                'a marked role group is a leftover, killed as a group',
                [
                    proc(200, 200, 'sh node_modules/.bin/tsx src/index.ts', MARKED_ENV),
                    proc(201, 200, 'node src/index.ts', MARKED_ENV),
                ],
                { groups: [200], pids: [], strangers: [] },
            ],
            [
                'an unmarked combined posthog-node started by path from anywhere is a stranger',
                [proc(300, 300, `bash ${REPO}/bin/posthog-node`, PLAIN_ENV, '/home/dev')],
                { groups: [], pids: [], strangers: [300] },
            ],
            [
                'an unmarked combined posthog-node started from the repo, after it moves into nodejs, is a stranger',
                [proc(301, 301, 'bash ./bin/posthog-node', PLAIN_ENV, NODEJS)],
                { groups: [], pids: [], strangers: [301] },
            ],
            [
                'an unmarked combined tsx src/index.ts in the nodejs dir is a stranger',
                [proc(310, 310, `node ${NODEJS}/node_modules/.bin/tsx watch src/index.ts`, PLAIN_ENV)],
                { groups: [], pids: [], strangers: [310] },
            ],
            [
                'an unmarked CDP-mode process is a stranger',
                [proc(311, 311, 'node tsx src/index.ts', modeEnv('cdp-processed-events'))],
                { groups: [], pids: [], strangers: [311] },
            ],
            [
                'an unmarked local-cdp process is a stranger',
                [proc(315, 315, 'node tsx src/index.ts', modeEnv('local-cdp'))],
                { groups: [], pids: [], strangers: [315] },
            ],
            [
                'an unmarked CDP mode outside the scenario roles is a stranger',
                [proc(316, 316, 'node tsx src/index.ts', modeEnv('cdp-cyclotron-worker'))],
                { groups: [], pids: [], strangers: [316] },
            ],
            [
                'an unmarked process whose capability groups include CDP is a stranger',
                [proc(317, 317, 'node tsx src/index.ts', [...PLAIN_ENV, 'NODEJS_CAPABILITY_GROUPS=cdp_workflows'])],
                { groups: [], pids: [], strangers: [317] },
            ],
            [
                'an unmarked process that only runs the feature flags group is not a stranger',
                [proc(318, 318, 'node tsx src/index.ts', [...PLAIN_ENV, 'NODEJS_CAPABILITY_GROUPS=feature_flags'])],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                "the workflows stack's push-api posthog-node is not a stranger",
                [proc(312, 312, 'bash ./bin/posthog-node', modeEnv('push-api'), NODEJS)],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                "the workflows stack's ingestion process is not a stranger",
                [proc(313, 313, 'node tsx watch src/index.ts', modeEnv('ingestion-v2-combined'))],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                "another project's tsx src/index.ts is not a stranger",
                [proc(314, 314, 'node tsx src/index.ts', PLAIN_ENV, '/work/other-app')],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                "another user's process on this checkout's entry point, whose cwd and environ are unreadable, is a stranger",
                [proc(320, 320, `node ${NODEJS}/src/index.ts`, null, null)],
                { groups: [], pids: [], strangers: [320] },
            ],
            [
                "another user's process on a relative entry point, whose cwd and environ are unreadable, is ignored",
                [proc(321, 321, 'node dist/index.js', null, null)],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                'an unreadable environ on anything else is ignored',
                [proc(330, 330, 'postgres: checkpointer', null, '/var/lib/postgresql')],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                'an unrelated unmarked process is ignored',
                [proc(340, 340, 'node server.js', PLAIN_ENV)],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                'a marked process in a group with an unmarked one is killed alone',
                [proc(400, 400, 'bash', PLAIN_ENV), proc(401, 400, 'node src/index.ts', MARKED_ENV)],
                { groups: [], pids: [401], strangers: [] },
            ],
            [
                "a marked process in the runner's own group is killed alone",
                [proc(500, SELF, 'node -e leftover', MARKED_ENV)],
                { groups: [], pids: [500], strangers: [] },
            ],
        ])('%s', (_name, entries, expected) => {
            const plan = planCleanup([runner, ...entries], SELF, NODEJS)

            expect({ ...plan, strangers: plan.strangers.map((entry) => entry.pid) }).toEqual(expected)
        })

        it('never targets the runner itself, even when it carries the marker', () => {
            const plan = planCleanup([proc(SELF, SELF, 'node scenarios run smoke', MARKED_ENV)], SELF, NODEJS)

            expect(plan).toEqual({ groups: [], pids: [], strangers: [] })
        })
    })

    it('names the stop command for every stranger', () => {
        const error = strangerConflict([
            proc(41, 41, 'bash ./bin/posthog-node', PLAIN_ENV, REPO),
            proc(42, 41, 'node src/index.ts', PLAIN_ENV),
        ])

        expect(error).toMatchObject({ exitCode: 2 })
        expect(error.message).toContain('Run `kill 41 42`, then run the scenario again.')
    })

    describe('roleSpecs', () => {
        const base = { PATH: '/usr/bin', AWS_PROFILE: 'prod-admin', HTTP_SERVER_PORT: '6738' }
        const specs = roleSpecs(base, 'http://127.0.0.1:4566', secretsOf({}))

        it('gives every role its own port, cdp-api the one Django calls', () => {
            const ports = Object.fromEntries(specs.map((spec) => [spec.role, spec.env.HTTP_SERVER_PORT]))

            expect(Object.keys(ports).sort()).toEqual([...CdpRole.options].sort())
            expect(new Set(Object.values(ports)).size).toBe(CdpRole.options.length)
            expect(ports['cdp-api']).toBe('6738')
        })

        it.each(CdpRole.options)('runs %s as itself in dev, marked, against the edge, without AWS_PROFILE', (role) => {
            const { env } = specs.find((spec) => spec.role === role)!

            expect(env).not.toHaveProperty('AWS_PROFILE')
            expect(env).toMatchObject({
                PATH: '/usr/bin',
                NODE_ENV: 'dev',
                PLUGIN_SERVER_MODE: role,
                SES_ENDPOINT: 'http://127.0.0.1:4566',
                SCENARIO_RUNNER: '1',
            })
        })

        it("shares the runner's secrets with the roles", () => {
            const [spec] = roleSpecs(
                {},
                'http://edge',
                secretsOf({ ENCRYPTION_SALT_KEYS: 'run-key', WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'run-jwt' })
            )

            expect(spec.env).toMatchObject({
                ENCRYPTION_SALT_KEYS: 'run-key',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'run-jwt',
            })
        })
    })

    it.each<[string, string, number | null]>([
        [
            'a group with members',
            'GROUP        cdp-processed-events-consumer\nCOORDINATOR  0\nSTATE        Stable\nBALANCER     range\nMEMBERS      2\nTOTAL-LAG    0\n',
            2,
        ],
        [
            'an empty group',
            'GROUP        cdp-processed-events-consumer\nSTATE        Empty\nMEMBERS      0\nTOTAL-LAG    0\n',
            0,
        ],
        [
            'a group that never existed',
            'GROUP        cdp-processed-events-consumer\nCOORDINATOR  0\nSTATE        Dead\nBALANCER     \nMEMBERS      0\nTOTAL-LAG    0\n',
            0,
        ],
        ['output it cannot read', 'unable to dial: dial tcp 127.0.0.1:9092: connect: connection refused\n', null],
    ])('reads the members of %s from rpk', (_name, output, members) => {
        expect(membersOf(output)).toBe(members)
    })

    it.each<[string, NodeJS.ProcessEnv, string]>([
        ['the default group', {}, 'cdp-processed-events-consumer'],
        ['a group the runner env overrides', { CDP_EVENTS_CONSUMER_GROUP_ID: 'scenario-events' }, 'scenario-events'],
    ])('checks the events role for %s', (_name, env, group) => {
        expect(eventsConsumerGroup(roleSpecs(env, 'http://edge', secretsOf({})))).toBe(group)
    })

    it('reports a Redis that accepts but never answers as down instead of hanging', async () => {
        const silent = net.createServer(() => {})
        await new Promise<void>((resolve) => silent.listen(0, '127.0.0.1', resolve))
        const { port } = silent.address() as net.AddressInfo
        try {
            await expect(pingRedis({ host: '127.0.0.1', port })).rejects.toThrow()
        } finally {
            silent.close()
        }
    }, 4_000)

    describe('run lock', () => {
        const children: ChildProcess[] = []

        afterEach(() => children.splice(0).forEach((child) => child.kill('SIGKILL')))

        const lockFromAnotherRunner = async (stateDir: string): Promise<{ child: ChildProcess; said: string }> => {
            const child = spawn(
                process.execPath,
                [
                    '--import',
                    'tsx',
                    '-e',
                    `require('./tests/scenarios/environment/processes').holdRunLock(${JSON.stringify(stateDir)}).then(
                         () => process.stdout.write('held'),
                         (error) => process.stdout.write(error.message)
                     )
                     setInterval(() => {}, 1000)`,
                ],
                { cwd: NODEJS_DIR, stdio: ['ignore', 'pipe', 'inherit'] }
            )
            children.push(child)
            const [said] = await once(child.stdout!, 'data')
            return { child, said: String(said) }
        }

        it('refuses a state dir a live runner holds, naming it, and takes it over once that runner dies', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            const other = await lockFromAnotherRunner(stateDir)
            expect(other.said).toBe('held')

            await expect(holdRunLock(stateDir)).rejects.toThrow(
                `Scenario runner ${other.child.pid} is already running from ${stateDir}. Run \`kill ${other.child.pid}\`, then run the scenario again.`
            )

            other.child.kill('SIGKILL')
            await once(other.child, 'exit')
            await (
                await holdRunLock(stateDir)
            )()
        }, 20_000)

        it('lets exactly one of several runners that start together hold the state dir', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            const runners = await Promise.all([1, 2, 3, 4].map(() => lockFromAnotherRunner(stateDir)))

            expect(runners.filter(({ said }) => said === 'held')).toHaveLength(1)
        }, 30_000)

        it('keeps holding the state dir when a peer hangs up before the answer', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            const other = await lockFromAnotherRunner(stateDir)
            const address = lockAddress(stateDir)
            await Promise.all(
                Array.from({ length: 50 }, async () => {
                    const socket = net.connect(address)
                    socket.on('error', () => undefined)
                    await once(socket, 'connect')
                    socket.destroy()
                })
            )

            await expect(holdRunLock(stateDir)).rejects.toThrow(`Scenario runner ${other.child.pid} is already running`)
        }, 20_000)

        it('names a suspended runner that holds the state dir, and how to stop it', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            const other = await lockFromAnotherRunner(stateDir)
            other.child.kill('SIGSTOP')

            await expect(holdRunLock(stateDir)).rejects.toMatchObject({
                exitCode: 2,
                message: expect.stringContaining(
                    `Scenario runner ${other.child.pid} holds ${stateDir} but does not answer; it may be suspended (resume it with fg). Run \`kill -CONT ${other.child.pid}; kill ${other.child.pid}\`, then run the scenario again.`
                ),
            })
        }, 20_000)

        it('frees the state dir for the next runner when released', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            await (
                await holdRunLock(stateDir)
            )()

            expect((await lockFromAnotherRunner(stateDir)).said).toBe('held')
        }, 20_000)
    })

    describe('leftover scan on real processes', () => {
        const children: ChildProcess[] = []
        const holdsPipeThroughChild = `
            const child = require('child_process').spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
                stdio: ['ignore', 'inherit', 'ignore'],
            })
            child.on('spawn', () => process.stdout.write('ready'))
            setInterval(() => {}, 1000)
        `

        const launch = async (env: NodeJS.ProcessEnv): Promise<ChildProcess> => {
            const child = spawn(process.execPath, ['-e', holdsPipeThroughChild], {
                env,
                detached: true,
                stdio: ['ignore', 'pipe', 'ignore'],
            })
            children.push(child)
            await once(child.stdout!, 'data')
            return child
        }

        afterEach(() => {
            children.splice(0).forEach((child) => {
                try {
                    process.kill(-child.pid!, 'SIGKILL')
                } catch {}
            })
        })

        it('kills the whole group of a marked role and leaves an unmarked sibling running', async () => {
            const [roleEnv] = roleSpecs(process.env, 'http://127.0.0.1:4566', secretsOf({}))
            const { SCENARIO_RUNNER: _marker, ...plainEnv } = process.env
            const marked = await launch(roleEnv.env)
            const unmarked = await launch(plainEnv)

            const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR)
            expect(plan.groups).toContain(marked.pid)
            expect([...plan.groups, ...plan.pids]).not.toContain(unmarked.pid)

            const groupGone = once(marked.stdout!, 'close')
            await terminate({ groups: plan.groups.filter((pgid) => pgid === marked.pid), pids: [] }, 5000)
            await groupGone

            expect(unmarked.exitCode).toBeNull()
            expect(() => process.kill(-unmarked.pid!, 0)).not.toThrow()
        }, 10_000)

        it('returns only once a group that ignores SIGTERM has let go of its port', async () => {
            const stubborn = spawn(
                process.execPath,
                [
                    '-e',
                    "process.on('SIGTERM', () => {}); const server = require('http').createServer().listen(0, '127.0.0.1', () => process.stdout.write(String(server.address().port)))",
                ],
                { detached: true, stdio: ['ignore', 'pipe', 'ignore'] }
            )
            children.push(stubborn)
            const port = Number(String((await once(stubborn.stdout!, 'data'))[0]))

            await terminate({ groups: [stubborn.pid!], pids: [] }, 200)

            expect(await isPortFree(port)).toBe(true)
        }, 10_000)
    })

    describe('up', () => {
        const cacheHome = process.env.XDG_CACHE_HOME
        const realSpawn = childProcess.spawn
        const realExecFile = childProcess.execFile as (...args: unknown[]) => ChildProcess
        const stubRolePids = new Set<number>()
        const stubRole =
            "require('http').createServer((_request, response) => response.end(String(process.pid))).listen(Number(process.env.HTTP_SERVER_PORT))"
        const stubRoleExitingAfterHealth =
            "let answered = false; require('http').createServer((_request, response) => (answered ? process.exit(1) : response.end(() => (answered = true)))).listen(Number(process.env.HTTP_SERVER_PORT))"
        const stubRoleBindingAfterHolder = `
            const port = Number(process.env.HTTP_SERVER_PORT)
            const bind = () =>
                require('net')
                    .connect(port, '127.0.0.1')
                    .once('connect', function () {
                        this.destroy()
                        require('http').createServer().listen(port)
                    })
                    .once('error', () => setTimeout(bind, 20))
            bind()
        `
        const templateSchema = `scenario_up_${process.pid}`
        const templatesUrl = inSchema(defaultConfig.DATABASE_URL, templateSchema)
        const insertTemplates = `INSERT INTO posthog_hogfunctiontemplate (id, template_id, sha, name, code, code_language, inputs_schema, type, status, category, free, created_at, updated_at) SELECT gen_random_uuid(), template_id, 'scenario', template_id, '', 'hog', '[]', 'destination', 'stable', '[]', true, now(), now() FROM unnest($1::text[]) AS template_id`
        const templatesInDjango = async (): Promise<string[]> =>
            await withPostgres(
                async (client) =>
                    (
                        await client.query<{ template_id: string }>(
                            'SELECT template_id FROM posthog_hogfunctiontemplate ORDER BY template_id'
                        )
                    ).rows.map((row) => row.template_id),
                templatesUrl
            )
        const fakeHogli = `
            const fs = require('fs')
            const path = require('path')
            const args = process.argv.slice(2)
            const command = args.join(' ')
            const flags = { with: [], without: [] }
            const words = []
            for (let i = 0; i < args.length; i++) {
                const [flag, inline] = args[i].split('=')
                if (['--with', '--without', '--custom', '--timeout'].includes(flag)) {
                    const value = inline ?? args[++i]
                    const name = flag.slice(2)
                    Array.isArray(flags[name]) ? flags[name].push(value) : (flags[name] = value)
                } else {
                    words.push(args[i])
                }
            }
            const stateFile = path.join(__dirname, 'stack.json')
            const stack = JSON.parse(fs.readFileSync(stateFile, 'utf8'))
            const fail = (why) => {
                process.stderr.write(why + '\\n')
                process.exit(1)
            }
            const verb = words.join(' ')
            if (verb === 'wait') {
                if (flags.timeout === '0') {
                    process.exit(stack.ready ? 0 : 3)
                }
                if (!stack.running) {
                    fail('No stack runs')
                }
                fs.writeFileSync(stateFile, JSON.stringify({ running: true, ready: true }))
            } else if (verb === 'dev:generate') {
                const units = ['backend', 'frontend', 'nodejs', ...flags.with].filter((unit) => !flags.without.includes(unit))
                fs.writeFileSync(
                    process.env.HOGLI_MPROCS_PATH,
                    'procs:\\n' + units.map((unit) => '  ' + unit + ':\\n    shell: bin/start-' + unit + '\\n').join('')
                )
            } else if (verb === 'up -d' && flags.custom) {
                if (stack.running) {
                    fail('phrocs: detached phrocs already running')
                }
                if (!fs.existsSync(flags.custom)) {
                    fail('No mprocs config at ' + flags.custom)
                }
                if (/^  nodejs:/m.test(fs.readFileSync(flags.custom, 'utf8'))) {
                    fail('The config at ' + flags.custom + ' starts nodejs')
                }
                fs.writeFileSync(stateFile, JSON.stringify({ running: true, ready: false }))
            } else if (command === 'dev:sync-hog-templates') {
                const { Client } = require(${JSON.stringify(require.resolve('pg'))})
                const client = new Client({ connectionString: ${JSON.stringify(templatesUrl)} })
                client
                    .connect()
                    .then(() => client.query(${JSON.stringify(insertTemplates)}, [${JSON.stringify(STACK.templates)}]))
                    .then(() => client.end())
                    .then(
                        () => process.exit(0),
                        (error) => fail(String(error))
                    )
            } else {
                fail('The fake hogli has no command ' + command)
            }
        `
        const fakeDocker = `
            const fs = require('fs')
            const path = require('path')
            const args = process.argv.slice(2)
            const [exec, container, rpk, noun, verb, group] = args
            if (args.length !== 6 || [exec, container, rpk, noun, verb].join(' ') !== 'exec posthog-kafka-1 rpk group describe') {
                process.stderr.write('The fake docker has no command ' + args.join(' ') + '\\n')
                process.exit(1)
            }
            const members = Number(fs.readFileSync(path.join(__dirname, 'members'), 'utf8'))
            process.stdout.write(
                'GROUP        ' + group + '\\nCOORDINATOR  0\\nSTATE        ' + (members > 0 ? 'Stable' : 'Empty') +
                    '\\nBALANCER     range\\nMEMBERS      ' + members + '\\nTOTAL-LAG    0\\n'
            )
            const answers = path.join(__dirname, 'answers')
            fs.writeFileSync(answers, String((fs.existsSync(answers) ? Number(fs.readFileSync(answers, 'utf8')) : 0) + 1))
        `
        let fakes = ''
        let cacheDir = ''
        let stranger: ChildProcess | undefined
        let environment: Environment | undefined
        let portHolder: http.Server | undefined
        let unspawnable: Role | undefined
        let losesItsPort: Role | undefined
        let exitsAfterHealth: Role | undefined
        let reachedKafka: Error | undefined

        const logOf = (role: Role): string => path.join(process.env.XDG_CACHE_HOME!, 'posthog-scenarios', `${role}.log`)
        const healthOf = async (role: Role): Promise<number> =>
            (await internalFetch(`http://127.0.0.1:${ROLE_PORTS[role]}/_health`)).status
        const holdPort = async (role: Role, answersAfter: Promise<unknown> = Promise.resolve()): Promise<void> => {
            portHolder = http.createServer((_request, response) => void answersAfter.then(() => response.end()))
            await new Promise<void>((resolve) => portHolder!.listen(ROLE_PORTS[role], '127.0.0.1', resolve))
        }
        const answerMembers = (members: number): void => writeFileSync(path.join(fakes, 'members'), String(members))
        const answersSoFar = (): number =>
            existsSync(path.join(fakes, 'answers')) ? Number(readFileSync(path.join(fakes, 'answers'), 'utf8')) : 0
        const writeStack = (stack: { running: boolean; ready: boolean }): void =>
            writeFileSync(path.join(fakes, 'stack.json'), JSON.stringify(stack))
        const stackOf = (): { running: boolean; ready: boolean } =>
            parseJSON(readFileSync(path.join(fakes, 'stack.json'), 'utf8'))
        const environmentOf = (): Environment =>
            createEnvironment({
                hogli: { command: path.join(fakes, 'hogli'), cwd: fakes },
                docker: path.join(fakes, 'docker'),
                postgresUrl: templatesUrl,
            })

        beforeAll(async () => {
            await withPostgres(async (client) => {
                await client.query(`DROP SCHEMA IF EXISTS ${templateSchema} CASCADE`)
                await client.query(`CREATE SCHEMA ${templateSchema}`)
                await client.query(
                    `CREATE TABLE ${templateSchema}.posthog_hogfunctiontemplate (LIKE public.posthog_hogfunctiontemplate INCLUDING ALL)`
                )
            }, defaultConfig.DATABASE_URL)
        })

        afterAll(async () => {
            await withPostgres(
                (client) => client.query(`DROP SCHEMA IF EXISTS ${templateSchema} CASCADE`),
                defaultConfig.DATABASE_URL
            )
        })

        beforeEach(async () => {
            fakes = mkdtempSync(path.join(os.tmpdir(), 'scenario-fakes-'))
            writeFake(path.join(fakes, 'hogli'), fakeHogli)
            writeFake(path.join(fakes, 'docker'), fakeDocker)
            writeStack({ running: true, ready: true })
            answerMembers(0)
            await withPostgres(async (client) => {
                await client.query('DELETE FROM posthog_hogfunctiontemplate')
                await client.query(insertTemplates, [STACK.templates])
            }, templatesUrl)
            const realTerminate = processes.terminate
            jest.spyOn(processes, 'terminate').mockImplementation((plan, graceMs) => {
                const foreign = [...plan.groups, ...plan.pids].filter((pid) => !stubRolePids.has(pid))
                return foreign.length > 0
                    ? Promise.reject(new Error(`The up test would kill ${foreign.join(', ')}.`))
                    : realTerminate(plan, graceMs)
            })
            jest.spyOn(childProcess, 'spawn').mockImplementation(((
                command: string,
                args: string[],
                options: SpawnOptions
            ) => {
                if (command.endsWith(path.join('bin', 'hogli')) && command !== path.join(fakes, 'hogli')) {
                    throw new Error('The up test reached the dev stack.')
                }
                if (!command.endsWith(path.join('node_modules', '.bin', 'tsx'))) {
                    return realSpawn(command, args, options)
                }
                if (options.env?.PLUGIN_SERVER_MODE === unspawnable) {
                    return realSpawn(path.join(NODEJS_DIR, 'no-such-tsx'), args, options)
                }
                const mode = options.env?.PLUGIN_SERVER_MODE
                const script =
                    mode === losesItsPort
                        ? stubRoleBindingAfterHolder
                        : mode === exitsAfterHealth
                          ? stubRoleExitingAfterHealth
                          : stubRole
                const role = realSpawn(process.execPath, ['-e', script], options)
                if (mode === losesItsPort) {
                    void holdPort(losesItsPort!, once(role, 'exit'))
                    losesItsPort = undefined
                }
                if (mode === exitsAfterHealth) {
                    exitsAfterHealth = undefined
                }
                stubRolePids.add(role.pid!)
                return role
            }) as unknown as typeof childProcess.spawn)
            const guardedExecFile = jest.spyOn(childProcess, 'execFile').mockImplementation(((
                file: string,
                ...rest: unknown[]
            ) => {
                if (file !== path.join(fakes, 'docker')) {
                    reachedKafka ??= new Error(
                        `The up test ran ${file} ${(rest[0] as string[]).join(' ')} instead of the fake docker.`
                    )
                    throw reachedKafka
                }
                return realExecFile(file, ...rest)
            }) as unknown as typeof childProcess.execFile) as unknown as (...args: unknown[]) => ChildProcess
            Object.defineProperty(guardedExecFile, promisify.custom, {
                value: (...args: unknown[]) =>
                    new Promise((resolve, reject) => {
                        guardedExecFile(...args, (error: Error | null, stdout: string, stderr: string) =>
                            error ? reject(error) : resolve({ stdout, stderr })
                        )
                    }),
            })
            cacheDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-cache-'))
            process.env.XDG_CACHE_HOME = cacheDir
        })

        afterEach(async () => {
            await environment?.down()
            environment = undefined
            portHolder?.close()
            portHolder = undefined
            unspawnable = undefined
            losesItsPort = undefined
            exitsAfterHealth = undefined
            jest.restoreAllMocks()
            stranger?.kill('SIGKILL')
            if (cacheHome === undefined) {
                delete process.env.XDG_CACHE_HOME
            } else {
                process.env.XDG_CACHE_HOME = cacheHome
            }
            rmSync(fakes, { recursive: true, force: true })
            rmSync(cacheDir, { recursive: true, force: true })
            const reached = reachedKafka
            reachedKafka = undefined
            if (reached) {
                throw reached
            }
        })

        it('waits for a dead consumer to leave the events group before it starts the roles', async () => {
            answerMembers(1)
            environment = environmentOf()
            let settled = false
            const upping = environment.up().finally(() => {
                settled = true
            })
            upping.catch(() => undefined)

            await waitForExpect(() => expect(answersSoFar()).toBeGreaterThan(1), 10_000)
            expect({ settled, apiPortFree: await isPortFree(ROLE_PORTS['cdp-api']) }).toEqual({
                settled: false,
                apiPortFree: true,
            })
            answerMembers(0)

            await expect(upping).resolves.toBeUndefined()
        }, 30_000)

        it.each<[string, boolean, string[]]>([
            ['a running stack', true, STACK.templates],
            ['a stack hogli cannot reach', false, STACK.templates],
            ['a stack whose Django lacks the templates', true, []],
        ])(
            'brings up %s through hogli and ends with the templates in Django',
            async (_name, running, templates) => {
                writeStack({ running, ready: running })
                await withPostgres(
                    (client) =>
                        client.query('DELETE FROM posthog_hogfunctiontemplate WHERE NOT (template_id = ANY($1))', [
                            templates,
                        ]),
                    templatesUrl
                )
                environment = environmentOf()

                await environment.up()

                expect({ stack: stackOf(), templates: await templatesInDjango() }).toEqual({
                    stack: { running: true, ready: true },
                    templates: [...STACK.templates].sort(),
                })
            },
            30_000
        )

        it('records a role that dies and starts it again', async () => {
            const role = 'cdp-processed-events'
            environment = environmentOf()
            await environment.up()
            const health = `http://127.0.0.1:${ROLE_PORTS[role]}/_health`
            const killed = Number(await (await internalFetch(health)).text())

            process.kill(killed, 'SIGKILL')

            await waitForExpect(async () => {
                const answer = await internalFetch(health)
                expect(answer.status).toBe(200)
                expect(Number(await answer.text())).not.toBe(killed)
            }, 15_000)
            expect(environment.exits()).toEqual([expect.objectContaining({ role, signal: 'SIGKILL', byValve: false })])
        }, 30_000)

        it('brings every role up healthy', async () => {
            environment = environmentOf()

            await environment.up()

            const health = await Promise.all(CdpRole.options.map(async (role) => [role, await healthOf(role)]))
            expect(Object.fromEntries(health)).toEqual(Object.fromEntries(CdpRole.options.map((role) => [role, 200])))
        }, 30_000)

        it.each<[string, Role, () => void]>([
            [
                'loses its port to another server that answers /_health',
                'cdp-processed-events',
                () => {
                    losesItsPort = 'cdp-processed-events'
                },
            ],
            [
                'answers /_health once, then exits',
                'cdp-api',
                () => {
                    exitsAfterHealth = 'cdp-api'
                },
            ],
            [
                'cannot be spawned',
                'cdp-cyclotron-worker-email',
                () => {
                    unspawnable = 'cdp-cyclotron-worker-email'
                },
            ],
        ])(
            'fails naming a role that %s and its log',
            async (_name, role, arrange) => {
                arrange()
                environment = environmentOf()

                const failure = await environment.up().then(
                    () => null,
                    (error: Error) => error.message
                )

                expect(failure).toMatch(new RegExp(`^${role} `))
                expect(failure).toContain(logOf(role))
            },
            30_000
        )

        it('refuses a role port another server already answers on, naming the port and how to see its holder', async () => {
            await holdPort('cdp-processed-events')
            environment = environmentOf()

            await expect(environment.up()).rejects.toMatchObject({
                exitCode: 2,
                message: expect.stringMatching(
                    /6760 \(cdp-processed-events\)\. Find the processes that hold them with `ss -ltnp 'sport = :6760'`, stop them, then run the scenario again\.$/
                ),
            })
        }, 30_000)

        it('refuses a stranger again when retried after a refused up, instead of reporting itself as the holder', async () => {
            const {
                SCENARIO_RUNNER: _marker,
                PLUGIN_SERVER_MODE: _mode,
                NODEJS_CAPABILITY_GROUPS: _groups,
                ...plainEnv
            } = process.env
            stranger = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)', 'src/index.ts'], {
                cwd: NODEJS_DIR,
                env: plainEnv,
                stdio: 'ignore',
            })
            await once(stranger, 'spawn')
            const environment = createEnvironment()
            const refusal = {
                exitCode: 2,
                message: expect.stringMatching(
                    new RegExp(`Run \`kill (\\d+ )*${stranger.pid}( \\d+)*\`, then run the scenario again\\.$`)
                ),
            }

            await expect(environment.up()).rejects.toMatchObject(refusal)
            await expect(environment.up()).rejects.toMatchObject(refusal)
        }, 20_000)
    })
})
