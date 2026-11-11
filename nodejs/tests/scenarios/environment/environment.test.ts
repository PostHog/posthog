import { ChildProcess, spawn } from 'child_process'
import { once } from 'events'
import { mkdirSync, mkdtempSync, readFileSync, rmdirSync } from 'fs'
import net from 'net'
import os from 'os'
import path from 'path'
import { setTimeout as nextTimers } from 'timers/promises'

import { SES_RATE_LIMIT_KEY } from '~/cdp/services/job-queue/job-queue-rate-limited-postgres-v2'
import { RateLimiterService } from '~/cdp/services/rate-limiter/rate-limiter.service'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { waitForExpect } from '~/tests/helpers/expectations'

import { CdpRole } from '../cards'
import { createEnvironment } from './environment'
import * as processes from './processes'
import { ProcEntry, holdRunLock, lockAddress, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ROLE_PORTS, consumerGroupsOf, roleSpecs, secretsOf } from './roles'
import * as stack from './stack'
import { forgetSesBucket, membersOf, pingRedis, seekFailures } from './stack'
import { createSupervisor } from './supervisor'

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

const stateOf = (pid: number): string => {
    const stat = readFileSync(`/proc/${pid}/stat`, 'utf8')
    return stat.slice(stat.lastIndexOf(')') + 2, stat.lastIndexOf(')') + 3)
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
                SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                SES_RATE_LIMITER_VALKEY_PORT: '6390',
                ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'local-dev-workflows-transactional-email-jwt',
                SCENARIO_RUNNER: '1',
            })
        })

        it('lets profile settings override the role environment but not how the runner wires a role', () => {
            const settings = {
                SES_REGION: 'eu-west-1',
                CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: '900',
                SES_ENDPOINT: 'http://elsewhere',
                PERSONHOG_ADDR: '127.0.0.1:1',
                SES_RATE_LIMITER_VALKEY_HOST: 'elsewhere',
                SES_RATE_LIMITER_VALKEY_PORT: '6379',
                ENCRYPTION_SALT_KEYS: 'profile-key',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'profile-jwt',
                PLUGIN_SERVER_MODE: 'ingestion-v2',
                HTTP_SERVER_PORT: '1',
                PGAPPNAME: 'other',
                SCENARIO_RUNNER: '0',
            }
            const [spec] = roleSpecs(base, 'http://127.0.0.1:4566', secretsOf({}), settings)

            expect(spec.env).toMatchObject({
                SES_REGION: 'eu-west-1',
                CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: '900',
                SES_ENDPOINT: 'http://127.0.0.1:4566',
                PERSONHOG_ADDR: '127.0.0.1:50052',
                SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                SES_RATE_LIMITER_VALKEY_PORT: '6390',
                ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'local-dev-workflows-transactional-email-jwt',
                PLUGIN_SERVER_MODE: spec.role,
                HTTP_SERVER_PORT: String(ROLE_PORTS[spec.role]),
                PGAPPNAME: `scenario-${spec.role}`,
                SCENARIO_RUNNER: '1',
            })
        })

        it('drops an inherited consumer group id, so the events role joins the group a reset moves', () => {
            const specs = roleSpecs({ KAFKA_CONSUMER_GROUP_ID: 'dev-group' }, 'http://edge', secretsOf({}))

            expect(specs.filter(({ env }) => 'KAFKA_CONSUMER_GROUP_ID' in env)).toEqual([])
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

    it.each<[string, NodeJS.ProcessEnv, Record<string, string>, { group: string; topics: string[] }[]]>([
        [
            'the events consumer on its configured topic',
            {},
            {},
            [
                {
                    group: 'cdp-processed-events-consumer',
                    topics: ['clickhouse_events_json'],
                },
            ],
        ],
        [
            'the group the runner env overrides',
            { CDP_EVENTS_CONSUMER_GROUP_ID: 'scenario-events' },
            {},
            [{ group: 'scenario-events', topics: ['clickhouse_events_json'] }],
        ],
        [
            'the events topic under the Kafka prefix the roles inherit',
            { KAFKA_PREFIX: 'scenario_' },
            {},
            [{ group: 'cdp-processed-events-consumer', topics: ['scenario_clickhouse_events_json'] }],
        ],
        [
            'the group and topic a profile sets',
            {},
            { CDP_EVENTS_CONSUMER_GROUP_ID: 'scenario-events', CDP_EVENTS_CONSUMER_TOPIC: 'scenario_events_json' },
            [{ group: 'scenario-events', topics: ['scenario_events_json'] }],
        ],
    ])('moves %s', (_name, env, settings, groups) => {
        expect(consumerGroupsOf(roleSpecs(env, 'http://edge', secretsOf({}), settings))).toEqual(groups)
    })

    it.each<[string, string, string[]]>([
        [
            'a clean seek of a group that never committed',
            'TOPIC                   PARTITION  PRIOR-OFFSET  CURRENT-OFFSET\nclickhouse_events_json  0          -1            0\n',
            [],
        ],
        [
            'a partition the broker refused while the group has a member',
            'TOPIC                   PARTITION  PRIOR-OFFSET  CURRENT-OFFSET  ERROR\nclickhouse_events_json  0          -1            -1              INVALID_OPERATION: seeking a non-empty group is not allowed.\n',
            ['clickhouse_events_json/0: INVALID_OPERATION: seeking a non-empty group is not allowed.'],
        ],
        [
            'a topic that does not exist yet, so has nothing to skip',
            'unable to list all offsets successfully: UNKNOWN_TOPIC_OR_PARTITION: This server does not host this topic-partition.\n',
            [],
        ],
        [
            'a seek rpk could not run',
            'unable to fetch offsets for "scenario-probe-t4-nobroker": unable to dial: dial tcp 127.0.0.1:1: connect: connection refused\n',
            [
                'unable to fetch offsets for "scenario-probe-t4-nobroker": unable to dial: dial tcp 127.0.0.1:1: connect: connection refused',
            ],
        ],
    ])('reads the partition errors of %s from rpk', (_name, output, failures) => {
        expect(seekFailures(output)).toEqual(failures)
    })

    it('refills the SES token bucket the email worker claims from, so a reset starts with a full one', async () => {
        const valkey = createRedisV2PoolFromConfig({
            connection: { url: '127.0.0.1', options: { port: 6379 } },
            poolMinSize: 1,
            poolMaxSize: 1,
        })
        const limiter = new RateLimiterService(valkey, { name: 'scenario-reset' })
        const claim = { key: SES_RATE_LIMIT_KEY, requested: 5, capacity: 5, refillPerSecond: 0.001 }
        try {
            await limiter.claimUpTo(claim)
            expect(await limiter.claimUpTo(claim)).toBe(0)

            await forgetSesBucket({ host: '127.0.0.1', port: 6379 })

            expect(await limiter.claimUpTo(claim)).toBe(5)
        } finally {
            await forgetSesBucket({ host: '127.0.0.1', port: 6379 })
        }
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

            await expect(holdRunLock(stateDir)).rejects.toThrow(`Scenario runner ${other.child.pid} is already running`)

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
                    `Scenario runner ${other.child.pid} holds ${stateDir} but does not answer`
                ),
                stopCommand: `kill -CONT ${other.child.pid}; kill ${other.child.pid}`,
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

        it('resumes a frozen group so it stops on SIGTERM instead of waiting for SIGKILL', async () => {
            const frozen = await launch(process.env)
            process.kill(-frozen.pid!, 'SIGSTOP')
            while (stateOf(frozen.pid!) !== 'T') {
                await new Promise(setImmediate)
            }
            const exited = once(frozen, 'exit')

            await terminate({ groups: [frozen.pid!], pids: [] }, 5000)

            expect(await exited).toEqual([null, 'SIGTERM'])
        }, 15_000)
    })

    describe('role supervisor on real processes', () => {
        const tag = `stop-${process.pid}`
        const tagged = (): ProcEntry[] =>
            readProcs().filter((entry) => entry.environ?.includes(`SCENARIO_TEST_TAG=${tag}`))
        const supervisor = createSupervisor({
            command: process.execPath,
            args: ['-e', 'setInterval(() => {}, 1000)'],
            cwd: os.tmpdir(),
            logDir: mkdtempSync(path.join(os.tmpdir(), 'scenario-logs-')),
            graceMs: 5000,
            restartBackoffMs: 0,
        })

        afterEach(() => supervisor.stop())

        it('stops a running role without recording its exit or starting it again', async () => {
            const [spec] = roleSpecs(process.env, 'http://127.0.0.1:4566', secretsOf({}))
            await supervisor.start([{ ...spec, env: { ...spec.env, SCENARIO_TEST_TAG: tag } }])
            expect(tagged()).toHaveLength(1)

            await supervisor.stop()
            await nextTimers(0)

            expect({ exits: supervisor.exits(), running: tagged() }).toEqual({ exits: [], running: [] })
        }, 15_000)

        it('records a role it cannot start again and keeps retrying until it starts', async () => {
            const cwd = mkdtempSync(path.join(os.tmpdir(), 'scenario-role-cwd-'))
            const exiting = createSupervisor({
                command: process.execPath,
                args: ['-e', 'process.exit(3)'],
                cwd,
                logDir: mkdtempSync(path.join(os.tmpdir(), 'scenario-logs-')),
                graceMs: 1000,
                restartBackoffMs: 50,
            })
            const [spec] = roleSpecs(process.env, 'http://127.0.0.1:4566', secretsOf({}))
            try {
                await exiting.start([spec])
                rmdirSync(cwd)
                await waitForExpect(
                    () =>
                        expect(exiting.exits().map(({ error }) => error)).toContainEqual(
                            expect.stringContaining('ENOENT')
                        ),
                    5000,
                    20
                )
                mkdirSync(cwd)
                const failedStarts = exiting.exits().length

                await waitForExpect(
                    () =>
                        expect(
                            exiting
                                .exits()
                                .slice(failedStarts)
                                .map(({ code }) => code)
                        ).toContain(3),
                    5000,
                    20
                )
            } finally {
                await exiting.stop()
            }
        }, 15_000)
    })

    describe('up', () => {
        const cacheHome = process.env.XDG_CACHE_HOME
        let stranger: ChildProcess | undefined

        beforeEach(() => {
            const realTerminate = processes.terminate
            jest.spyOn(processes, 'terminate').mockImplementation((plan, graceMs) =>
                plan.groups.length + plan.pids.length > 0
                    ? Promise.reject(new Error(`The up test would kill ${[...plan.groups, ...plan.pids].join(', ')}.`))
                    : realTerminate(plan, graceMs)
            )
            jest.spyOn(stack, 'startStack').mockRejectedValue(new Error('The up test reached the dev stack.'))
        })

        afterEach(() => {
            jest.restoreAllMocks()
            stranger?.kill('SIGKILL')
            if (cacheHome === undefined) {
                delete process.env.XDG_CACHE_HOME
            } else {
                process.env.XDG_CACHE_HOME = cacheHome
            }
        })

        it('refuses a stranger again when retried after a refused up, instead of reporting itself as the holder', async () => {
            process.env.XDG_CACHE_HOME = mkdtempSync(path.join(os.tmpdir(), 'scenario-cache-'))
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
            const refusal = { stopCommand: expect.stringMatching(new RegExp(`^kill (\\d+ )*${stranger.pid}( \\d+)*$`)) }

            await expect(environment.up()).rejects.toMatchObject(refusal)
            await expect(environment.up()).rejects.toMatchObject(refusal)
        }, 20_000)
    })
})
