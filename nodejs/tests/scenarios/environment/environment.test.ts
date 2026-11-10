import { ChildProcess, spawn } from 'child_process'
import { once } from 'events'
import { mkdtempSync, rmSync } from 'fs'
import net from 'net'
import os from 'os'
import path from 'path'

import { CdpRole } from '../cards'
import { ProcEntry, holdRunLock, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { roleSpecs, secretsOf } from './roles'
import { eventsConsumerGroup, membersOf, phrocsSocketPath, pingRedis, stackCommands, stackIsLive } from './stack'

const SELF = 100
const REPO = '/work/posthog'
const NODEJS = `${REPO}/nodejs`
const MARKED_ENV = ['PATH=/usr/bin', 'SCENARIO_RUNNER=1']
const PLAIN_ENV = ['PATH=/usr/bin']
const modeEnv = (mode: string): string[] => [...PLAIN_ENV, `PLUGIN_SERVER_MODE=${mode}`]
const NODEJS_DIR = path.resolve(__dirname, '..', '..', '..')

const proc = (pid: number, pgid: number, cmdline: string, environ: string[] | null, cwd = NODEJS): ProcEntry => ({
    pid,
    pgid,
    cmdline,
    cwd,
    environ,
})

const runner = proc(SELF, SELF, 'node scenarios run smoke', PLAIN_ENV)

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
                'an unmarked combined posthog-node from the repo is a stranger',
                [proc(300, 300, 'bash ./bin/posthog-node', PLAIN_ENV, REPO)],
                { groups: [], pids: [], strangers: [300] },
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
                "the workflows stack's push-api posthog-node is not a stranger",
                [proc(312, 312, 'bash ./bin/posthog-node', modeEnv('push-api'), REPO)],
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
                'an unreadable environ on a CDP entry point is a stranger, never a leftover',
                [proc(320, 320, 'node src/index.ts', null)],
                { groups: [], pids: [], strangers: [320] },
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

        expect(error).toMatchObject({ exitCode: 2, stopCommand: 'kill 41 42' })
        expect(error.message).toContain('Stop it with `kill 41 42`')
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

        it.each(CdpRole.options)('gives %s the full role environment without AWS_PROFILE', (role) => {
            const { env } = specs.find((spec) => spec.role === role)!

            expect(env).toEqual({
                PATH: '/usr/bin',
                NODE_ENV: 'dev',
                PLUGIN_SERVER_MODE: role,
                HTTP_SERVER_PORT: env.HTTP_SERVER_PORT,
                PGAPPNAME: `scenario-${role}`,
                SES_ENDPOINT: 'http://127.0.0.1:4566',
                SES_REGION: 'us-east-1',
                AWS_ACCESS_KEY_ID: 'scenario',
                AWS_SECRET_ACCESS_KEY: 'scenario',
                PERSONHOG_ENABLED: 'true',
                PERSONHOG_ADDR: '127.0.0.1:50052',
                ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'local-dev-workflows-transactional-email-jwt',
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
        ['a group that never existed', 'GROUP  cdp-processed-events-consumer\nERROR  GROUP_ID_NOT_FOUND\n', 0],
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

    it.each<[string, boolean, string[]]>([
        ['launches a stack when none is live', false, ['dev:generate', 'up', 'wait']],
        ['reuses a live stack and only waits for it', true, ['wait']],
    ])('%s', (_name, live, commands) => {
        expect(stackCommands('/state/mprocs.yaml', live).map(([command]) => command)).toEqual(commands)
    })

    describe('detached stack liveness', () => {
        const children: ChildProcess[] = []
        const servers: net.Server[] = []
        const sockets: string[] = []

        afterEach(async () => {
            children.splice(0).forEach((child) => child.kill('SIGKILL'))
            sockets.splice(0).forEach((socket) => rmSync(socket, { force: true }))
            await Promise.all(servers.splice(0).map((server) => new Promise((resolve) => server.close(resolve))))
        })

        const listenAt = async (socket: string): Promise<void> => {
            const server = net.createServer()
            servers.push(server)
            await new Promise<void>((resolve) => server.listen(socket, resolve))
        }

        const leaveStaleSocketAt = async (socket: string): Promise<void> => {
            const child = spawn(
                process.execPath,
                [
                    '-e',
                    `require('net').createServer().listen(${JSON.stringify(socket)}, () => process.stdout.write('up'))`,
                ],
                {
                    stdio: ['ignore', 'pipe', 'ignore'],
                }
            )
            children.push(child)
            await once(child.stdout!, 'data')
            child.kill('SIGKILL')
            await once(child, 'exit')
        }

        it.each<[string, (socket: string) => Promise<void>, boolean]>([
            ['a phrocs socket that answers is live', listenAt, true],
            ['a socket file a killed phrocs left behind is not live', leaveStaleSocketAt, false],
            ['no socket is not live', async () => {}, false],
        ])('%s', async (_name, arrange, live) => {
            const repoRoot = mkdtempSync(path.join(os.tmpdir(), 'scenario-repo-'))
            const socket = phrocsSocketPath(repoRoot)
            sockets.push(socket)
            await arrange(socket)

            expect(await stackIsLive(repoRoot)).toBe(live)
        })
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
                    `try { require('./tests/scenarios/environment/processes').holdRunLock(${JSON.stringify(stateDir)}); process.stdout.write('held') }
                     catch (error) { process.stdout.write(error.message) }
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

            expect(() => holdRunLock(stateDir)).toThrow(`Scenario runner ${other.child.pid} is already running`)

            other.child.kill('SIGKILL')
            await once(other.child, 'exit')
            expect(() => holdRunLock(stateDir)).not.toThrow()
        }, 20_000)

        it('frees the state dir for the next runner when released', async () => {
            const stateDir = mkdtempSync(path.join(os.tmpdir(), 'scenario-state-'))
            holdRunLock(stateDir)()

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
    })
})
