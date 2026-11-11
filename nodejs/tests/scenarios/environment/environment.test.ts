import childProcess, { ChildProcess, SpawnOptions, spawn } from 'child_process'
import { once } from 'events'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'fs'
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
const STATE_DIR = '/home/dev/.cache/posthog-scenarios'
const MARKED_ENV = ['PATH=/usr/bin', `SCENARIO_RUNNER=${STATE_DIR}`]
const PLAIN_ENV = ['PATH=/usr/bin']
const OTHER_CHECKOUT = '/work/posthog-other/nodejs'
const OTHER_MARKED_ENV = ['PATH=/usr/bin', 'SCENARIO_RUNNER=/home/other/.cache/posthog-scenarios']
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
                'a role group another runner marked for its own state dir, from another checkout, is a stranger and survives',
                [
                    proc(210, 210, 'sh node_modules/.bin/tsx src/index.ts', OTHER_MARKED_ENV, OTHER_CHECKOUT),
                    proc(211, 210, 'node src/index.ts', OTHER_MARKED_ENV, OTHER_CHECKOUT),
                ],
                { groups: [], pids: [], strangers: [210, 211] },
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
                'an unmarked node that tsx re-execs with its loaders on src/index.ts is a stranger',
                [
                    proc(
                        319,
                        319,
                        `/opt/node/bin/node --require ${REPO}/node_modules/tsx/dist/preflight.cjs --import file://${REPO}/node_modules/tsx/dist/loader.mjs src/index.ts`,
                        PLAIN_ENV
                    ),
                ],
                { groups: [], pids: [], strangers: [319] },
            ],
            [
                'an unmarked tsx watcher launched through its pnpm shim is a stranger',
                [proc(322, 322, `node ${NODEJS}/node_modules/.bin/../tsx/dist/cli.mjs watch src/index.ts`, PLAIN_ENV)],
                { groups: [], pids: [], strangers: [322] },
            ],
            [
                'an unmarked node whose options take separate values before the entry point is a stranger',
                [
                    proc(323, 323, 'node --title cdp dist/index.js', PLAIN_ENV),
                    proc(324, 324, 'node --env-file ../.env dist/index.js', PLAIN_ENV),
                    proc(325, 325, 'node --inspect-port 9230 --import tsx src/index.ts', PLAIN_ENV),
                    proc(
                        326,
                        326,
                        'node --max-old-space-size 4096 --redirect-warnings /tmp/cdp.log dist/index.js',
                        PLAIN_ENV
                    ),
                    proc(327, 327, 'tsx --tsconfig tsconfig.json src/index.ts', PLAIN_ENV),
                    proc(328, 328, 'tsx watch --include src src/index.ts', PLAIN_ENV),
                    proc(329, 329, 'tsx watch --ignore **/*.test.ts src/index.ts', PLAIN_ENV),
                    proc(330, 330, 'tsx watch --exclude src/generated.ts src/index.ts', PLAIN_ENV),
                ],
                { groups: [], pids: [], strangers: [323, 324, 325, 326, 327, 328, 329, 330] },
            ],
            [
                'an unmarked node whose short options only resemble inline code is a stranger',
                [
                    proc(331, 331, 'node -rperf_hooks --import tsx src/index.ts', PLAIN_ENV),
                    proc(332, 332, 'node -prof dist/index.js', PLAIN_ENV),
                ],
                { groups: [], pids: [], strangers: [331, 332] },
            ],
            [
                'an editor open on the entry point in the nodejs dir is not a stranger',
                [proc(350, 350, 'vim src/index.ts', PLAIN_ENV), proc(351, 351, 'less ../bin/posthog-node', PLAIN_ENV)],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                'a shell command that only names the entry point is not a stranger',
                [proc(352, 352, 'bash -c vim src/index.ts', PLAIN_ENV)],
                { groups: [], pids: [], strangers: [] },
            ],
            [
                'a node or tsx script or inline code that takes the entry point as an argument is not a stranger',
                [
                    proc(353, 353, 'node node_modules/typescript/bin/tsc src/index.ts', PLAIN_ENV),
                    proc(
                        354,
                        354,
                        `node ${NODEJS}/node_modules/.bin/tsx watch scripts/lint.ts src/index.ts`,
                        PLAIN_ENV
                    ),
                    proc(355, 355, 'tsx scripts/lint.tsx src/index.ts', PLAIN_ENV),
                    proc(356, 356, 'node -e require("fs").watch(process.argv[1],()=>{}) src/index.ts', PLAIN_ENV),
                    proc(357, 357, 'node --print 1 src/index.ts', PLAIN_ENV),
                    proc(359, 359, 'node --eval=require("fs").watch(process.argv[1],()=>{}) src/index.ts', PLAIN_ENV),
                    proc(360, 360, 'node -pe process.argv[1] src/index.ts', PLAIN_ENV),
                    proc(
                        358,
                        358,
                        'node --max-old-space-size=4096 node_modules/typescript/bin/tsc src/index.ts',
                        PLAIN_ENV
                    ),
                ],
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
            const plan = planCleanup([runner, ...entries], SELF, NODEJS, STATE_DIR)

            expect({ ...plan, strangers: plan.strangers.map((entry) => entry.pid) }).toEqual(expected)
        })

        it('never targets the runner itself, even when it carries the marker', () => {
            const plan = planCleanup(
                [proc(SELF, SELF, 'node scenarios run smoke', MARKED_ENV)],
                SELF,
                NODEJS,
                STATE_DIR
            )

            expect(plan).toEqual({ groups: [], pids: [], strangers: [] })
        })
    })

    it('names the stop command for every stranger', async () => {
        const error = await strangerConflict([
            proc(41, 41, 'bash ./bin/posthog-node', PLAIN_ENV, REPO),
            proc(42, 41, 'node src/index.ts', PLAIN_ENV),
        ])

        expect(error).toMatchObject({ exitCode: 2 })
        expect(error.message).toContain('Run `kill 41 42`, then run the scenario again.')
    })

    describe('roleSpecs', () => {
        const base = { PATH: '/usr/bin', AWS_PROFILE: 'prod-admin', HTTP_SERVER_PORT: '6738' }
        const specs = roleSpecs(base, 'http://127.0.0.1:4566', secretsOf({}), STATE_DIR)

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
                SCENARIO_RUNNER: STATE_DIR,
            })
        })

        it("shares the runner's secrets with the roles", () => {
            const [spec] = roleSpecs(
                {},
                'http://edge',
                secretsOf({ ENCRYPTION_SALT_KEYS: 'run-key', WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'run-jwt' }),
                STATE_DIR
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
        expect(eventsConsumerGroup(roleSpecs(env, 'http://edge', secretsOf({}), STATE_DIR))).toBe(group)
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

    it('reports a running Kafka as up when the probes run under tsx like the CLI', async () => {
        const probe = `import('./tests/scenarios/environment/stack').then(({ downServices }) => downServices(undefined, 'postgres://127.0.0.1:1/none')).then((down) => console.log(JSON.stringify(down)))`
        const { stdout } = await promisify(childProcess.execFile)(
            path.join(NODEJS_DIR, 'node_modules', '.bin', 'tsx'),
            ['-e', probe],
            { cwd: NODEJS_DIR }
        )
        const down: string[] = parseJSON(stdout.trim().split('\n').pop() ?? '[]')
        expect({ postgres: down.includes('postgres'), kafka: down.includes('kafka') }).toEqual({
            postgres: true,
            kafka: false,
        })
    }, 30_000)

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

        it('names the process that holds the state dir, not what it answers, when the answer is not a pid', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            const impostor = net.createServer((socket) => socket.end('1; rm -rf ~'))
            await new Promise<void>((resolve) => impostor.listen(lockAddress(stateDir), resolve))
            try {
                const refusal = await holdRunLock(stateDir).catch((error: Error & { exitCode?: number }) => error)

                expect(refusal).toMatchObject({ exitCode: 2 })
                expect((refusal as Error).message).toBe(
                    `Process ${process.pid} holds ${stateDir} but does not answer with a pid; it may be a suspended scenario runner (resume it with fg). Run \`kill -CONT ${process.pid}; kill ${process.pid}\`, then run the scenario again.`
                )
            } finally {
                impostor.close()
            }
        }, 20_000)

        it('names a suspended runner that holds the state dir, and how to stop it', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            const other = await lockFromAnotherRunner(stateDir)
            other.child.kill('SIGSTOP')

            await expect(holdRunLock(stateDir)).rejects.toMatchObject({
                exitCode: 2,
                message: expect.stringContaining(
                    `Process ${other.child.pid} holds ${stateDir} but does not answer with a pid; it may be a suspended scenario runner (resume it with fg). Run \`kill -CONT ${other.child.pid}; kill ${other.child.pid}\`, then run the scenario again.`
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
        describe('roles another runner marked', () => {
            const rolesOf = (stateDir: string): ProcEntry[] => {
                const environ = ['PATH=/usr/bin', `SCENARIO_RUNNER=${stateDir}`]
                return [
                    proc(210, 210, 'sh node_modules/.bin/tsx src/index.ts', environ, OTHER_CHECKOUT),
                    proc(211, 210, 'node src/index.ts', environ, OTHER_CHECKOUT),
                ]
            }
            const listedRoles = '210 (sh node_modules/.bin/tsx src/index.ts), 211 (node src/index.ts)'

            it('names the runner and its roles in one kill while that runner holds its state dir', async () => {
                const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
                const other = await lockFromAnotherRunner(stateDir)

                const error = await strangerConflict(rolesOf(stateDir))

                expect(error).toMatchObject({ exitCode: 2 })
                expect(error.message).toBe(
                    `Roles of scenario runner ${other.child.pid}, which uses ${stateDir}, are running: ${listedRoles}. That runner restarts roles that are killed, so run \`kill ${other.child.pid} 210 211\`, then run the scenario again.`
                )
            }, 20_000)

            it('resumes a suspended runner before killing it and its roles', async () => {
                const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
                const other = await lockFromAnotherRunner(stateDir)
                other.child.kill('SIGSTOP')

                const error = await strangerConflict(rolesOf(stateDir))

                expect(error.message).toBe(
                    `Roles of scenario runner ${other.child.pid}, which uses ${stateDir} but does not answer with a pid and may be suspended, are running: ${listedRoles}. That runner restarts roles that are killed, so run \`kill -CONT ${other.child.pid}; kill ${other.child.pid} 210 211\`, then run the scenario again.`
                )
            }, 20_000)

            it('names the kill command for its roles once no runner holds its state dir', async () => {
                const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))

                const error = await strangerConflict([
                    ...rolesOf(stateDir),
                    proc(41, 41, 'bash ./bin/posthog-node', PLAIN_ENV, REPO),
                ])

                expect(error.message).toBe(
                    `CDP processes the scenario runner did not start are running: ${listedRoles}, 41 (bash ./bin/posthog-node). Use \`hogli down\` if hogli started them. Run \`kill 210 211 41\`, then run the scenario again.`
                )
            })
        })
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
            const stateDir = path.join(os.tmpdir(), `scenario-leftovers-${process.pid}`)
            const [roleEnv] = roleSpecs(process.env, 'http://127.0.0.1:4566', secretsOf({}), stateDir)
            const { SCENARIO_RUNNER: _marker, ...plainEnv } = process.env
            const marked = await launch(roleEnv.env)
            const unmarked = await launch(plainEnv)

            const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR, stateDir)
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
        let rolesSpawnedWhileHeld = 0
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
            const { values: flags, positionals } = require('util').parseArgs({
                args,
                allowPositionals: true,
                options: {
                    with: { type: 'string', multiple: true, default: [] },
                    without: { type: 'string', multiple: true, default: [] },
                    custom: { type: 'string' },
                    timeout: { type: 'string' },
                    d: { type: 'boolean' },
                },
            })
            const stateFile = path.join(__dirname, 'stack.json')
            const stack = JSON.parse(fs.readFileSync(stateFile, 'utf8'))
            const fail = (why) => {
                process.stderr.write(why + '\\n')
                process.exit(1)
            }
            const verb = positionals.join(' ')
            if (verb === 'wait') {
                if (flags.timeout !== undefined) {
                    const answers = stack.running && !(stack.busy && Number(flags.timeout) <= 30)
                    process.exit(!answers ? 3 : stack.ready ? 0 : 2)
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
            } else if (verb === 'up' && flags.d && flags.custom) {
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
            } else if (verb === 'dev:sync-hog-templates') {
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
            fs.appendFileSync(path.join(__dirname, 'describes'), '.')
            const members = fs.existsSync(path.join(__dirname, 'dead-member-held')) ? 1 : 0
            process.stdout.write(
                'GROUP        ' + group + '\\nCOORDINATOR  0\\nSTATE        ' + (members > 0 ? 'Stable' : 'Empty') +
                    '\\nBALANCER     range\\nMEMBERS      ' + members + '\\nTOTAL-LAG    0\\n'
            )
        `
        let fakes = ''
        let cacheDir = ''
        let stranger: ChildProcess | undefined
        let leftover: ChildProcess | undefined
        let environment: Environment | undefined
        let portHolder: http.Server | undefined
        let unspawnable: Role | undefined
        let losesItsPort: Role | undefined
        let exitsAfterHealth: Role | undefined
        let reachedKafka: Error | undefined

        const logOf = (role: Role): string => path.join(process.env.XDG_CACHE_HOME!, 'posthog-scenarios', `${role}.log`)
        const healthOf = async (role: Role): Promise<number> =>
            (await internalFetch(`http://127.0.0.1:${ROLE_PORTS[role]}/_health`)).status
        const holdPort = async (port: number, answersAfter: Promise<unknown> = Promise.resolve()): Promise<void> => {
            portHolder = http.createServer((_request, response) => void answersAfter.then(() => response.end()))
            await new Promise<void>((resolve) => portHolder!.listen(port, '127.0.0.1', resolve))
        }
        const bindWithoutListening = async (port: number): Promise<() => void> => {
            const holder = spawn(
                'python3',
                [
                    '-c',
                    "import socket,sys,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', int(sys.argv[1]))); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0); print('bound', flush=True); time.sleep(60)",
                    String(port),
                ],
                { stdio: ['ignore', 'pipe', 'inherit'] }
            )
            const said = await new Promise<string>((resolve, reject) => {
                holder.once('error', reject)
                holder.once('exit', (code) => reject(new Error(`python3 exited with ${code} before it bound the port`)))
                holder.stdout!.once('data', (chunk) => resolve(String(chunk).trim()))
            })
            if (said !== 'bound') {
                holder.kill('SIGKILL')
                throw new Error(`python3 said ${said} instead of bound`)
            }
            return () => holder.kill('SIGKILL')
        }
        const holdDeadMember = (): void => writeFileSync(path.join(fakes, 'dead-member-held'), '')
        const releaseDeadMember = (): void => rmSync(path.join(fakes, 'dead-member-held'))
        const describeCount = (): number => {
            const describes = path.join(fakes, 'describes')
            return existsSync(describes) ? readFileSync(describes, 'utf8').length : 0
        }
        const writeStack = (stack: { running: boolean; ready: boolean; busy?: boolean }): void =>
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
            rolesSpawnedWhileHeld = 0
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
                if (existsSync(path.join(fakes, 'dead-member-held'))) {
                    rolesSpawnedWhileHeld += 1
                }
                const role = realSpawn(process.execPath, ['-e', script], options)
                if (mode === losesItsPort) {
                    void holdPort(ROLE_PORTS[losesItsPort!], once(role, 'exit'))
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
                            error ? reject(Object.assign(error, { stdout, stderr })) : resolve({ stdout, stderr })
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
            leftover?.kill('SIGKILL')
            leftover = undefined
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
            holdDeadMember()
            environment = environmentOf()

            const up = environment.up().then(
                () => 'up',
                (error: unknown) => String(error)
            )
            await waitForExpect(() => expect(describeCount()).toBeGreaterThanOrEqual(3), 10_000, 50)
            releaseDeadMember()

            expect({
                rolesSpawnedWhileHeld,
                up: await up,
                apiHealth: await healthOf('cdp-api'),
            }).toEqual({
                rolesSpawnedWhileHeld: 0,
                up: 'up',
                apiHealth: 200,
            })
        }, 30_000)

        it.each<[string, { running: boolean; ready: boolean; busy?: boolean }, string[]]>([
            ['a running stack', { running: true, ready: true }, STACK.templates],
            [
                'a running stack whose phrocs answers slowly, without starting it again',
                { running: true, ready: true, busy: true },
                STACK.templates,
            ],
            [
                'a stack that is still starting, without starting it again',
                { running: true, ready: false },
                STACK.templates,
            ],
            ['a stack hogli cannot reach', { running: false, ready: false }, STACK.templates],
            ['a stack whose Django lacks the templates', { running: true, ready: true }, []],
        ])(
            'brings up %s through hogli and ends with the templates in Django',
            async (_name, stack, templates) => {
                writeStack(stack)
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

        const answerOn = async (port: number): Promise<() => void> => {
            await holdPort(port)
            return () => undefined
        }
        it.each<[string, string, number, (port: number) => Promise<() => void>]>([
            ['answers on', 'cdp-processed-events', ROLE_PORTS['cdp-processed-events'], answerOn],
            [
                'binds without listening on',
                'cdp-processed-events',
                ROLE_PORTS['cdp-processed-events'],
                bindWithoutListening,
            ],
            ['answers on', 'provider edge', 4566, answerOn],
            ['binds without listening on', 'provider edge', 4566, bindWithoutListening],
        ])(
            'refuses a port another process %s, held for %s, naming the port and how to see its holder',
            async (_how, owner, port, hold) => {
                const release = await hold(port)
                try {
                    environment = environmentOf()

                    await expect(environment.up()).rejects.toMatchObject({
                        exitCode: 2,
                        message: expect.stringContaining(
                            `${port} (${owner}). Find the processes that hold them with \`ss -ltnp 'sport = :${port}'\`, stop them, then run the scenario again.`
                        ),
                    })
                } finally {
                    release()
                }
            },
            30_000
        )

        it('cleans up its own leftover role when its cache home is reached through a symlink', async () => {
            const stateDir = path.join(cacheDir, 'posthog-scenarios')
            mkdirSync(stateDir)
            const role = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
                env: { ...process.env, SCENARIO_RUNNER: stateDir },
                detached: true,
                stdio: 'ignore',
            })
            leftover = role
            await once(role, 'spawn')
            stubRolePids.add(role.pid!)
            const linked = path.join(fakes, 'cache-link')
            symlinkSync(cacheDir, linked)
            process.env.XDG_CACHE_HOME = linked
            environment = environmentOf()

            await environment.up()

            await waitForExpect(() => expect(role.signalCode).toBe('SIGTERM'), 5_000)
        }, 30_000)

        it('refuses a stranger again when retried after a refused up, instead of reporting itself as the holder', async () => {
            const {
                SCENARIO_RUNNER: _marker,
                PLUGIN_SERVER_MODE: _mode,
                NODEJS_CAPABILITY_GROUPS: _groups,
                ...plainEnv
            } = process.env
            const hold = path.join(fakes, 'hold.cjs')
            writeFileSync(hold, 'Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0)')
            stranger = spawn(process.execPath, ['--require', hold, 'src/index.ts'], {
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
