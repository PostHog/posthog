import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import childProcess, { ChildProcess, SpawnOptions, spawn } from 'child_process'
import { once } from 'events'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, rmdirSync, symlinkSync, writeFileSync } from 'fs'
import http from 'http'
import Redis from 'ioredis'
import net from 'net'
import os from 'os'
import path from 'path'
import { Client } from 'pg'
import { setTimeout as nextTimers } from 'timers/promises'
import { promisify } from 'util'

import { SES_RATE_LIMIT_KEY } from '~/cdp/services/job-queue/job-queue-rate-limited-postgres-v2'
import { RateLimiterService } from '~/cdp/services/rate-limiter/rate-limiter.service'
import { defaultConfig } from '~/common/config/config'
import { RedisClient, RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'
import { isPortFree } from '~/tests/helpers/service-process'

import { CdpRole } from '../cards'
import { Environment, createEnvironment } from './environment'
import * as processes from './processes'
import {
    ProcEntry,
    holdRunLock,
    lockAddress,
    planCleanup,
    processState,
    readProcs,
    strangerConflict,
    terminate,
} from './processes'
import { ROLE_PORTS, Role, consumerGroupsOf, fetchRetriesOf, roleSpecs, secretsOf } from './roles'
import {
    STACK,
    downServices,
    forgetSesBucket,
    lagOf,
    membersOf,
    pingRedis,
    postgresServersOf,
    scratchSchema,
    seekFailures,
    terminateRoleConnections,
    withPostgres,
} from './stack'
import { createSupervisor } from './supervisor'

const SELF = 100
const REPO = '/work/posthog'
const NODEJS = `${REPO}/nodejs`
const STATE_DIR = '/home/dev/.cache/posthog-scenarios'
const EDGE = { url: 'http://127.0.0.1:4566', caCertPath: `${STATE_DIR}/edge-ca/ca.pem` }
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

const writeFake = (file: string, body: string): void => {
    writeFileSync(file, `#!${process.execPath}\n${body}`, { mode: 0o755 })
}

const sendThrough = async (edgeUrl: string): Promise<string> => {
    const ses = new SESv2Client({
        endpoint: edgeUrl,
        region: 'us-east-1',
        credentials: { accessKeyId: 'edge', secretAccessKey: 'edge' },
        maxAttempts: 1,
    })
    try {
        await ses.send(
            new SendEmailCommand({
                FromEmailAddress: 'flows@www.example.com',
                Destination: { ToAddresses: ['run-1-1@www.example.com'] },
                Content: { Simple: { Subject: { Data: 'Hello' }, Body: { Text: { Data: 'Hello there' } } } },
            })
        )
        return 'sent'
    } catch (error) {
        return (error as Error).name
    } finally {
        ses.destroy()
    }
}

const sesLimiterOn = ({
    host,
    port,
}: {
    host: string
    port: number
}): { limiter: RateLimiterService; close: () => Promise<void> } => {
    const client = new Redis({ host, port, lazyConnect: true, maxRetriesPerRequest: 0 })
    const valkey: RedisV2 = {
        useClient: async (_options, use) => await use(client as unknown as RedisClient),
        usePipeline: async (_options, build) => {
            const pipeline = client.pipeline()
            build(pipeline as unknown as RedisClientPipeline)
            return await pipeline.exec()
        },
    }
    return {
        limiter: new RateLimiterService(valkey, { name: 'scenario-reset' }),
        close: async () => {
            await client.quit()
        },
    }
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
        const base = {
            PATH: '/usr/bin',
            AWS_PROFILE: 'prod-admin',
            HTTP_SERVER_PORT: '6738',
            EXTERNAL_REQUEST_PROXY_TEAMS: '2',
        }
        const specs = roleSpecs(base, EDGE, secretsOf({}), STATE_DIR)

        const POSTHOG = 'postgres://posthog:posthog@localhost:5432/posthog'

        it.each<[string, Record<string, string>, string[]]>([
            [
                'one server when Cyclotron shares it',
                { CYCLOTRON_NODE_DATABASE_URL: 'postgres://posthog:posthog@localhost:5432/cyclotron' },
                [POSTHOG],
            ],
            [
                'one server when Cyclotron spells the same server another way',
                { CYCLOTRON_NODE_DATABASE_URL: 'postgres://posthog:posthog@127.0.0.1/cyclotron' },
                [POSTHOG],
            ],
            [
                'one server when a setting holds the word postgres rather than a URL',
                { POSTHOG_DB_USER: 'postgres' },
                [POSTHOG],
            ],
            [
                'both servers when a profile moves Cyclotron to another',
                { CYCLOTRON_NODE_DATABASE_URL: 'postgres://posthog:posthog@cyclotron.example.com:5432/cyclotron' },
                [POSTHOG, 'postgres://posthog:posthog@cyclotron.example.com:5432/cyclotron'],
            ],
            [
                'both servers when a profile moves the read replica to another',
                { DATABASE_READONLY_URL: 'postgres://posthog:posthog@replica.example.com:5432/posthog' },
                [POSTHOG, 'postgres://posthog:posthog@replica.example.com:5432/posthog'],
            ],
        ])('lists the Postgres servers the roles reach: %s', (_story, settings, servers) => {
            const [spec] = roleSpecs(base, EDGE, secretsOf({}), STATE_DIR, settings)

            expect(postgresServersOf(spec, POSTHOG)).toEqual(servers)
        })

        const hogflowWorker = (settings: Record<string, string>) =>
            roleSpecs(base, EDGE, secretsOf({}), STATE_DIR, settings).find(
                ({ role }) => role === 'cdp-cyclotron-worker-hogflow'
            )!

        it.each<[string, Record<string, string>, number]>([
            ['the default', {}, 3],
            ['a profile setting', { CDP_FETCH_RETRIES: '5' }, 5],
        ])('reads the fetch retries of the hogflow worker from %s', (_story, settings, retries) => {
            expect(fetchRetriesOf(hogflowWorker(settings))).toBe(retries)
        })

        it('refuses fetch retries that are not a number', () => {
            expect(() => fetchRetriesOf(hogflowWorker({ CDP_FETCH_RETRIES: 'many' }))).toThrow(
                'CDP_FETCH_RETRIES many is not a number of retries'
            )
        })

        it('gives every role its own port, cdp-api the one Django calls', () => {
            const ports = Object.fromEntries(specs.map((spec) => [spec.role, spec.env.HTTP_SERVER_PORT]))

            expect(Object.keys(ports).sort()).toEqual([...CdpRole.options].sort())
            expect(new Set(Object.values(ports)).size).toBe(CdpRole.options.length)
            expect(ports['cdp-api']).toBe('6738')
        })

        it.each(CdpRole.options)(
            'runs %s as itself in dev, marked, against the edge and its proxy for every team, without AWS_PROFILE',
            (role) => {
                const { env } = specs.find((spec) => spec.role === role)!

                expect(env).not.toHaveProperty('AWS_PROFILE')
                expect(env).not.toHaveProperty('EXTERNAL_REQUEST_PROXY_TEAMS')
                expect(env).toMatchObject({
                    PATH: '/usr/bin',
                    NODE_ENV: 'dev',
                    PLUGIN_SERVER_MODE: role,
                    SES_ENDPOINT: EDGE.url,
                    HTTPS_PROXY: EDGE.url,
                    NODE_EXTRA_CA_CERTS: EDGE.caCertPath,
                    SCENARIO_RUNNER: STATE_DIR,
                })
            }
        )

        it('lets profile settings override the role environment but not how the runner wires a role', () => {
            const settings = {
                SES_REGION: 'eu-west-1',
                CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: '900',
                SES_ENDPOINT: 'http://elsewhere',
                HTTPS_PROXY: 'http://elsewhere',
                NODE_EXTRA_CA_CERTS: '/elsewhere/ca.pem',
                EXTERNAL_REQUEST_PROXY_TEAMS: '*:0.5',
                PERSONHOG_ADDR: '127.0.0.1:1',
                SES_RATE_LIMITER_VALKEY_HOST: 'elsewhere',
                SES_RATE_LIMITER_VALKEY_PORT: '6379',
                ENCRYPTION_SALT_KEYS: 'profile-key',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'profile-jwt',
                PLUGIN_SERVER_MODE: 'ingestion-v2',
                HTTP_SERVER_PORT: '1',
                PGAPPNAME: 'other',
                SCENARIO_RUNNER: '0',
                KAFKA_CONSUMER_GROUP_ID: 'scenario-events',
            }
            const [spec] = roleSpecs(base, EDGE, secretsOf({}), STATE_DIR, settings)

            expect(spec.env).not.toHaveProperty('KAFKA_CONSUMER_GROUP_ID')
            expect(spec.env).not.toHaveProperty('EXTERNAL_REQUEST_PROXY_TEAMS')
            expect(spec.env).toMatchObject({
                SES_REGION: 'eu-west-1',
                CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: '900',
                SES_ENDPOINT: EDGE.url,
                HTTPS_PROXY: EDGE.url,
                NODE_EXTRA_CA_CERTS: EDGE.caCertPath,
                PERSONHOG_ADDR: '127.0.0.1:50052',
                SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                SES_RATE_LIMITER_VALKEY_PORT: '6390',
                ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'local-dev-workflows-transactional-email-jwt',
                PLUGIN_SERVER_MODE: spec.role,
                HTTP_SERVER_PORT: String(ROLE_PORTS[spec.role]),
                PGAPPNAME: `scenario-${spec.role}`,
                SCENARIO_RUNNER: STATE_DIR,
            })
        })

        it('drops an inherited consumer group id, so the events role joins the group a reset moves', () => {
            const specs = roleSpecs(
                { KAFKA_CONSUMER_GROUP_ID: 'dev-group' },
                { url: 'http://edge' },
                secretsOf({}),
                STATE_DIR
            )

            expect(specs.filter(({ env }) => 'KAFKA_CONSUMER_GROUP_ID' in env)).toEqual([])
        })

        it("shares the runner's secrets with the roles", () => {
            const [spec] = roleSpecs(
                {},
                { url: 'http://edge' },
                secretsOf({ ENCRYPTION_SALT_KEYS: 'run-key', WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'run-jwt' }),
                STATE_DIR
            )

            expect(spec.env).toMatchObject({
                ENCRYPTION_SALT_KEYS: 'run-key',
                WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET: 'run-jwt',
            })
        })
    })

    it.each<[string, string, number | null, number | null]>([
        [
            'a group with members',
            'GROUP        cdp-processed-events-consumer\nCOORDINATOR  0\nSTATE        Stable\nBALANCER     range\nMEMBERS      2\nTOTAL-LAG    3\n',
            2,
            3,
        ],
        [
            'an empty group',
            'GROUP        cdp-processed-events-consumer\nSTATE        Empty\nMEMBERS      0\nTOTAL-LAG    0\n',
            0,
            0,
        ],
        [
            'a group that never existed',
            'GROUP        cdp-processed-events-consumer\nCOORDINATOR  0\nSTATE        Dead\nBALANCER     \nMEMBERS      0\nTOTAL-LAG    0\n',
            0,
            0,
        ],
        ['output it cannot read', 'unable to dial: dial tcp 127.0.0.1:9092: connect: connection refused\n', null, null],
    ])('reads the members and lag of %s from rpk', (_name, output, members, lag) => {
        expect(membersOf(output)).toBe(members)
        expect(lagOf(output)).toBe(lag)
    })

    it.each<[string, NodeJS.ProcessEnv, Record<string, string>, { group: string; topics: string[] }[]]>([
        [
            'the events consumer on its configured topic',
            {},
            {},
            [
                { group: 'cdp-processed-events-consumer', topics: ['clickhouse_events_json'] },
                { group: 'cdp-ses-webhooks-consumer', topics: ['cdp_ses_webhooks'] },
            ],
        ],
        [
            'the group the runner env overrides',
            { CDP_EVENTS_CONSUMER_GROUP_ID: 'scenario-events' },
            {},
            [
                { group: 'scenario-events', topics: ['clickhouse_events_json'] },
                { group: 'cdp-ses-webhooks-consumer', topics: ['cdp_ses_webhooks'] },
            ],
        ],
        [
            'the events topic under the Kafka prefix the roles inherit',
            { KAFKA_PREFIX: 'scenario_' },
            {},
            [
                { group: 'cdp-processed-events-consumer', topics: ['scenario_clickhouse_events_json'] },
                { group: 'cdp-ses-webhooks-consumer', topics: ['scenario_cdp_ses_webhooks'] },
            ],
        ],
        [
            'the group and topic a profile sets',
            {},
            { CDP_EVENTS_CONSUMER_GROUP_ID: 'scenario-events', CDP_EVENTS_CONSUMER_TOPIC: 'scenario_events_json' },
            [
                { group: 'scenario-events', topics: ['scenario_events_json'] },
                { group: 'cdp-ses-webhooks-consumer', topics: ['cdp_ses_webhooks'] },
            ],
        ],
    ])('moves %s', (_name, env, settings, groups) => {
        expect(consumerGroupsOf(roleSpecs(env, { url: 'http://edge' }, secretsOf({}), STATE_DIR, settings))).toEqual(
            groups
        )
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
        const { limiter, close } = sesLimiterOn({ host: '127.0.0.1', port: 6379 })
        const claim = { key: SES_RATE_LIMIT_KEY, requested: 5, capacity: 5, refillPerSecond: 0.001 }
        try {
            await limiter.claimUpTo(claim)
            expect(await limiter.claimUpTo(claim)).toBe(0)

            await forgetSesBucket({ host: '127.0.0.1', port: 6379 })

            expect(await limiter.claimUpTo(claim)).toBe(5)
        } finally {
            await forgetSesBucket({ host: '127.0.0.1', port: 6379 })
            await close()
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

    it('reports a running Kafka as up when the probes run under tsx like the CLI', async () => {
        const args: Parameters<typeof downServices> = [
            undefined,
            'postgres://127.0.0.1:1/none',
            { host: '127.0.0.1', port: 1 },
        ]
        const probe = `import('./tests/scenarios/environment/stack').then(({ downServices }) => downServices(...${JSON.stringify(args)})).then((down) => console.log(JSON.stringify(down)))`
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
            const [roleEnv] = roleSpecs(process.env, EDGE, secretsOf({}), stateDir)
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

        it('resumes a frozen group so it stops on SIGTERM instead of waiting for SIGKILL', async () => {
            const frozen = await launch(process.env)
            process.kill(-frozen.pid!, 'SIGSTOP')
            while (processState(frozen.pid!) !== 'T') {
                await new Promise(setImmediate)
            }
            const exited = once(frozen, 'exit')

            await terminate({ groups: [frozen.pid!], pids: [] }, 5000)

            expect(await exited).toEqual([null, 'SIGTERM'])
        }, 15_000)

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

    describe('role supervisor on real processes', () => {
        const tempRoot = mkdtempSync(path.join(os.tmpdir(), 'scenario-supervisor-'))
        const tag = `stop-${process.pid}`
        const tagged = (): ProcEntry[] =>
            readProcs().filter((entry) => entry.environ?.includes(`SCENARIO_TEST_TAG=${tag}`))
        const supervisor = createSupervisor({
            command: process.execPath,
            args: ['-e', 'setInterval(() => {}, 1000)'],
            cwd: os.tmpdir(),
            logDir: mkdtempSync(path.join(tempRoot, 'logs-')),
            graceMs: 5000,
            restartBackoffMs: 0,
        })

        afterEach(() => supervisor.stop())

        afterAll(() => rmSync(tempRoot, { recursive: true, force: true }))

        it('stops a running role without recording its exit or starting it again', async () => {
            const [spec] = roleSpecs(process.env, EDGE, secretsOf({}), STATE_DIR)
            await supervisor.start([{ ...spec, env: { ...spec.env, SCENARIO_TEST_TAG: tag } }])
            expect(tagged()).toHaveLength(1)

            await supervisor.stop()
            await nextTimers(0)

            expect({ exits: supervisor.exits(), running: tagged() }).toEqual({ exits: [], running: [] })
        }, 15_000)

        it('keeps a role stopped until the last of two overlapping freezes releases', async () => {
            const [spec] = roleSpecs(process.env, EDGE, secretsOf({}), STATE_DIR)
            await supervisor.start([{ ...spec, env: { ...spec.env, SCENARIO_TEST_TAG: tag } }])
            const [{ pid }] = tagged()
            const first = supervisor.freeze(spec.role, 5000)
            const second = supervisor.freeze(spec.role, 5000)
            expect(await second.observed()).toBe(true)

            await first.release()
            await first.release()
            const afterFirst = processState(pid)
            await second.release()
            await waitForExpect(() => expect(processState(pid)).not.toBe('T'), 5000, 20)

            expect(afterFirst).toBe('T')
        }, 15_000)

        it('records a role whose first start fails and retries it, instead of failing the start', async () => {
            const missing = createSupervisor({
                command: path.join(os.tmpdir(), `scenario-missing-${process.pid}`),
                args: [],
                cwd: os.tmpdir(),
                logDir: mkdtempSync(path.join(tempRoot, 'logs-')),
                graceMs: 1000,
                restartBackoffMs: 20,
            })
            const [spec] = roleSpecs(process.env, EDGE, secretsOf({}), STATE_DIR)
            try {
                await missing.start([spec])

                await waitForExpect(() => expect(missing.exits().length).toBeGreaterThanOrEqual(2), 5000, 20)
                expect(missing.exits()[0]).toMatchObject({ role: spec.role, error: expect.stringContaining('ENOENT') })
            } finally {
                await missing.stop()
            }
        }, 15_000)

        it('records a role it cannot start again and keeps retrying until it starts', async () => {
            const cwd = mkdtempSync(path.join(tempRoot, 'cwd-'))
            const exiting = createSupervisor({
                command: process.execPath,
                args: ['-e', 'process.exit(3)'],
                cwd,
                logDir: mkdtempSync(path.join(tempRoot, 'logs-')),
                graceMs: 1000,
                restartBackoffMs: 50,
            })
            const [spec] = roleSpecs(process.env, EDGE, secretsOf({}), STATE_DIR)
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

    describe('up and reset', () => {
        const cacheHome = process.env.XDG_CACHE_HOME
        const realSpawn = childProcess.spawn
        const realExecFile = childProcess.execFile as (...args: unknown[]) => ChildProcess
        const stubRolePids = new Set<number>()
        const STARTED_WHILE_HELD = 'started while the dead member was still in the events group'
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
        const templateSchema = scratchSchema(defaultConfig.DATABASE_URL, `scenario_up_${process.pid}`, [
            'posthog_hogfunctiontemplate',
        ])
        const templatesUrl = templateSchema.url
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
                const answersAfterS = stack.busy ? 10 : 0
                if (!stack.running || Number(flags.timeout ?? 300) < answersAfterS) {
                    process.exit(3)
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
            const [, , , , , , to, position, topicsFlag, topic, allowNew] = args
            const describes = args.length === 6 && verb === 'describe'
            const seeks =
                args.length === 11 &&
                verb === 'seek' &&
                to === '--to' &&
                ['start', 'end'].includes(position) &&
                topicsFlag === '--topics' &&
                allowNew === '--allow-new-topics'
            if ([exec, container, rpk, noun].join(' ') !== 'exec posthog-kafka-1 rpk group' || !(describes || seeks)) {
                process.stderr.write('The fake docker has no command ' + args.join(' ') + '\\n')
                process.exit(1)
            }
            const held = path.join(__dirname, 'dead-member-held')
            const leaving = path.join(__dirname, 'dead-member-leaving')
            if (describes && fs.existsSync(leaving)) {
                fs.rmSync(held, { force: true })
                fs.rmSync(leaving)
            }
            const members = fs.existsSync(held) ? 1 : 0
            if (seeks) {
                const answer = path.join(__dirname, 'seek')
                if (fs.existsSync(answer)) {
                    const { stdout, stderr, code } = JSON.parse(fs.readFileSync(answer, 'utf8'))
                    process.stdout.write(stdout)
                    process.stderr.write(stderr)
                    process.exit(code)
                }
                if (members > 0) {
                    process.stdout.write(
                        'TOPIC  PARTITION  PRIOR-OFFSET  CURRENT-OFFSET  ERROR\\n' +
                            topic + '  0          -1            -1              INVALID_OPERATION: seeking a non-empty group is not allowed.\\n'
                    )
                    process.exit(1)
                }
                const offsets = path.join(__dirname, 'offsets.json')
                const groups = fs.existsSync(offsets) ? JSON.parse(fs.readFileSync(offsets, 'utf8')) : {}
                groups[group] = { ...groups[group], [topic]: position }
                fs.writeFileSync(offsets, JSON.stringify(groups))
                process.stdout.write('TOPIC  PARTITION  PRIOR-OFFSET  CURRENT-OFFSET\\n' + topic + '  0  -1  0\\n')
                process.exit(0)
            }
            if (members > 0) {
                fs.writeFileSync(path.join(__dirname, 'held-member-seen'), '')
            }
            process.stdout.write(
                'GROUP        ' + group + '\\nCOORDINATOR  0\\nSTATE        ' + (members > 0 ? 'Stable' : 'Empty') +
                    '\\nBALANCER     range\\nMEMBERS      ' + members + '\\nTOTAL-LAG    0\\n'
            )
        `
        const jobsSchema = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_reset_${process.pid}`, [
            'cyclotron_jobs',
        ])
        const cyclotronUrl = jobsSchema.url
        const cyclotronFromEnv = process.env.CYCLOTRON_NODE_DATABASE_URL
        const testRedis = { host: '127.0.0.1', port: 6379 }
        const jobsLeft = async (): Promise<string[]> =>
            await withPostgres(
                async (client) =>
                    (
                        await client.query<{ status: string }>(
                            'SELECT status::text AS status FROM cyclotron_jobs ORDER BY status'
                        )
                    ).rows.map((row) => row.status),
                cyclotronUrl
            )
        const everyGroupAtEnd = (): Record<string, Record<string, string>> =>
            Object.fromEntries(
                consumerGroupsOf(roleSpecs(process.env, { url: 'http://edge' }, secretsOf({}), STATE_DIR)).map(
                    ({ group, topics }) => [group, Object.fromEntries(topics.map((topic) => [topic, 'end']))]
                )
            )
        const offsetsOf = (): Record<string, Record<string, string>> =>
            existsSync(path.join(fakes, 'offsets.json'))
                ? parseJSON(readFileSync(path.join(fakes, 'offsets.json'), 'utf8'))
                : {}
        let fakes = ''
        let cacheDir = ''
        let stranger: ChildProcess | undefined
        let leftover: ChildProcess | undefined
        let environment: Environment | undefined
        let portHolder: http.Server | undefined
        let unspawnable: Role | undefined
        let losesItsPort: Role | undefined
        let takesPortOnExit: Role | undefined
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
        const holdDeadMember = (): void => {
            rmSync(path.join(fakes, 'held-member-seen'), { force: true })
            writeFileSync(path.join(fakes, 'dead-member-held'), '')
        }
        const releaseDeadMember = (): void => writeFileSync(path.join(fakes, 'dead-member-leaving'), '')
        const untilMemberSeen = (settled: Promise<string>): Promise<string> =>
            Promise.race([
                waitForExpect(
                    () => expect(existsSync(path.join(fakes, 'held-member-seen'))).toBe(true),
                    20_000,
                    50
                ).then(() => 'member seen'),
                settled.then((outcome) => `settled before the release: ${outcome}`),
            ])
        const startedWhileMemberHeld = (): Role[] =>
            (Object.keys(ROLE_PORTS) as Role[]).filter(
                (role) => existsSync(logOf(role)) && readFileSync(logOf(role), 'utf8').includes(STARTED_WHILE_HELD)
            )
        const writeStack = (stack: { running: boolean; ready: boolean; busy?: boolean }): void =>
            writeFileSync(path.join(fakes, 'stack.json'), JSON.stringify(stack))
        const stackOf = (): { running: boolean; ready: boolean } =>
            parseJSON(readFileSync(path.join(fakes, 'stack.json'), 'utf8'))
        const environmentOf = (): Environment =>
            createEnvironment({
                hogli: { command: path.join(fakes, 'hogli'), cwd: fakes },
                docker: path.join(fakes, 'docker'),
                postgresUrl: templatesUrl,
                sesRateLimiterValkey: testRedis,
            })

        beforeAll(async () => {
            await templateSchema.create()
            await jobsSchema.create()
        })

        afterAll(async () => {
            await templateSchema.drop()
            await jobsSchema.drop()
        })

        beforeEach(async () => {
            fakes = mkdtempSync(path.join(os.tmpdir(), 'scenario-fakes-'))
            writeFake(path.join(fakes, 'hogli'), fakeHogli)
            writeFake(path.join(fakes, 'docker'), fakeDocker)
            writeStack({ running: true, ready: true })
            process.env.CYCLOTRON_NODE_DATABASE_URL = cyclotronUrl
            await withPostgres((client) => client.query('DELETE FROM cyclotron_jobs'), cyclotronUrl)
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
                const groupAtStart = `if (require('fs').existsSync(${JSON.stringify(path.join(fakes, 'dead-member-held'))})) console.log(${JSON.stringify(STARTED_WHILE_HELD)})\n`
                const role = realSpawn(process.execPath, ['-e', groupAtStart + script], options)
                if (mode === losesItsPort) {
                    void holdPort(ROLE_PORTS[losesItsPort!], once(role, 'exit'))
                    losesItsPort = undefined
                }
                if (mode === exitsAfterHealth) {
                    exitsAfterHealth = undefined
                }
                role.once('exit', () => {
                    if (takesPortOnExit !== undefined && mode === takesPortOnExit) {
                        void holdPort(ROLE_PORTS[takesPortOnExit])
                        takesPortOnExit = undefined
                    }
                })
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
            takesPortOnExit = undefined
            exitsAfterHealth = undefined
            if (cyclotronFromEnv === undefined) {
                delete process.env.CYCLOTRON_NODE_DATABASE_URL
            } else {
                process.env.CYCLOTRON_NODE_DATABASE_URL = cyclotronFromEnv
            }
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
            const seen = await untilMemberSeen(up)
            releaseDeadMember()

            expect({
                seen,
                up: await up,
                startedWhileMemberHeld: startedWhileMemberHeld(),
                health: await Promise.all(CdpRole.options.map((role) => healthOf(role).catch(String))),
            }).toEqual({
                seen: 'member seen',
                up: 'up',
                startedWhileMemberHeld: [],
                health: CdpRole.options.map(() => 200),
            })
        }, 45_000)

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

        it('kills a role on a valve, sees the old process gone, records the exit as the valve and starts it again', async () => {
            const role = 'cdp-cyclotron-worker-email'
            environment = environmentOf()
            await environment.up()
            const health = `http://127.0.0.1:${ROLE_PORTS[role]}/_health`
            const killed = Number(await (await internalFetch(health)).text())

            const actuation = await environment.actuate({ kind: 'kill', role })

            expect(await actuation.observed()).toBe(true)
            expect(() => process.kill(killed, 0)).toThrow()
            await waitForExpect(async () => {
                const answer = await internalFetch(health)
                expect(Number(await answer.text())).not.toBe(killed)
            }, 15_000)
            await actuation.release()
            expect(environment.exits()).toEqual([expect.objectContaining({ role, signal: 'SIGKILL', byValve: true })])
        }, 30_000)

        it("drops the roles' Postgres connections in every database on their servers and spares every other one", async () => {
            environment = environmentOf()
            await environment.up()
            const connect = async (
                url: string,
                applicationName: string
            ): Promise<{ client: Client; ended: Promise<void>; backend: number }> => {
                const client = new Client({ connectionString: url, application_name: applicationName })
                const ended = new Promise<void>((resolve) => client.on('error', () => resolve()))
                await client.connect()
                const backend = (await client.query<{ pid: number }>('SELECT pg_backend_pid() AS pid')).rows[0].pid
                return { client, ended, backend }
            }
            const tag = `${process.pid}-${Date.now()}`
            const pool = await connect(templatesUrl, 'cdp-cyclotron-worker-hogflow')
            const jobs = await connect(cyclotronUrl, `scenario-${tag}`)
            const bystanders = [
                await connect(templatesUrl, `bystander-${tag}`),
                await connect(cyclotronUrl, `bystander-${tag}`),
            ]
            const sessions = [pool, jobs, ...bystanders]
            try {
                const actuation = await environment.actuate({ kind: 'pg.terminate', share: 1 })

                expect(await actuation.observed()).toBe(true)
                await Promise.all([pool.ended, jobs.ended])
                const alive = await withPostgres(
                    async (client) =>
                        (
                            await client.query<{ pid: number }>(
                                'SELECT pid FROM pg_stat_activity WHERE pid = ANY($1::int[]) ORDER BY pid',
                                [sessions.map(({ backend }) => backend)]
                            )
                        ).rows.map(({ pid }) => pid),
                    templatesUrl
                )
                expect(alive).toEqual(bystanders.map(({ backend }) => backend).sort((x, y) => x - y))
                await actuation.release()
            } finally {
                await Promise.all(sessions.map(({ client }) => client.end().catch(() => undefined)))
            }
        }, 30_000)

        it('fails a drop that cannot reach the read replica, after dropping the role sessions on the main server', async () => {
            const readonlyFromEnv = process.env.DATABASE_READONLY_URL
            process.env.DATABASE_READONLY_URL = 'postgres://posthog:posthog@127.0.0.1:1/posthog'
            try {
                environment = environmentOf()
                await environment.up()
                const client = new Client({
                    connectionString: templatesUrl,
                    application_name: `scenario-${process.pid}-${Date.now()}`,
                })
                const ended = new Promise<void>((resolve) => client.on('error', () => resolve()))
                await client.connect()
                try {
                    await expect(environment.actuate({ kind: 'pg.terminate', share: 1 })).rejects.toThrow(
                        'ECONNREFUSED 127.0.0.1:1'
                    )
                    await ended
                } finally {
                    await client.end().catch(() => undefined)
                }
            } finally {
                if (readonlyFromEnv === undefined) {
                    delete process.env.DATABASE_READONLY_URL
                } else {
                    process.env.DATABASE_READONLY_URL = readonlyFromEnv
                }
            }
        }, 30_000)

        it("drops the dose's share of the roles' Postgres connections, rounded up", async () => {
            environment = environmentOf()
            await environment.up()
            const tag = `${process.pid}-${Date.now()}`
            const sessions = await Promise.all(
                [1, 2, 3].map(async (n) => {
                    const client = new Client({
                        connectionString: templatesUrl,
                        application_name: `scenario-${tag}-${n}`,
                    })
                    let ended = false
                    client.on('error', () => (ended = true))
                    await client.connect()
                    return { client, ended: () => ended }
                })
            )
            try {
                const terminated = await terminateRoleConnections(templatesUrl, 0.5)

                await waitForExpect(() => expect(sessions.filter(({ ended }) => ended())).toHaveLength(2))
                const answered = await Promise.all(
                    sessions
                        .filter(({ ended }) => !ended())
                        .map(async ({ client }) => (await client.query<{ one: number }>('SELECT 1 AS one')).rows[0].one)
                )
                expect({ terminated, answered }).toEqual({ terminated: 2, answered: [1] })
            } finally {
                await Promise.all(sessions.map(({ client }) => client.end().catch(() => undefined)))
            }
        })

        it('freezes a role on a valve, sees it stopped, and resumes the same process on release', async () => {
            const role = 'cdp-cyclotron-worker-hogflow'
            environment = environmentOf()
            await environment.up()
            const health = `http://127.0.0.1:${ROLE_PORTS[role]}/_health`
            const frozen = Number(await (await internalFetch(health)).text())

            const actuation = await environment.actuate({ kind: 'freeze', role })

            expect(await actuation.observed()).toBe(true)
            expect(processState(frozen)).toBe('T')
            await actuation.release()
            expect(Number(await (await internalFetch(health)).text())).toBe(frozen)
            expect(environment.exits()).toEqual([])
        }, 30_000)

        it('brings every role up healthy', async () => {
            environment = environmentOf()

            await environment.up()

            const health = await Promise.all(CdpRole.options.map(async (role) => [role, await healthOf(role)]))
            const edge = (await internalFetch(`${environment.edgeUrl()}/_health`)).status
            expect({ ...Object.fromEntries(health), edge }).toEqual({
                ...Object.fromEntries(CdpRole.options.map((role) => [role, 200])),
                edge: 200,
            })
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

        it.each<[string, () => Promise<void>]>([
            ['', async () => {}],
            [
                ' after a role crashed during the card',
                async () => {
                    process.kill([...stubRolePids].at(-1)!, 'SIGKILL')
                    await waitForExpect(() => expect(environment!.exits()).toHaveLength(1), 5_000)
                },
            ],
        ])(
            'brings every role back healthy on reset%s',
            async (_name, arrange) => {
                environment = environmentOf()
                await environment.up()
                await arrange()

                await environment.reset({})

                const health = await Promise.all(CdpRole.options.map(async (role) => [role, await healthOf(role)]))
                expect(Object.fromEntries(health)).toEqual(
                    Object.fromEntries(CdpRole.options.map((role) => [role, 200]))
                )
            },
            30_000
        )

        it("starts the next card without the last card's unfinished jobs, spent SES tokens or events backlog", async () => {
            const { limiter, close } = sesLimiterOn(testRedis)
            const claim = { key: SES_RATE_LIMIT_KEY, requested: 5, capacity: 5, refillPerSecond: 0.001 }
            environment = environmentOf()
            await environment.up()
            await withPostgres(
                (client) =>
                    client.query(
                        "INSERT INTO cyclotron_jobs (id, team_id, queue_name, status, priority, scheduled, created, last_transition) SELECT gen_random_uuid(), 9999001, 'hog', status::public.cyclotronjobstatus, 0, now(), now(), now() FROM unnest($1::text[]) AS status",
                        [['available', 'running', 'completed']]
                    ),
                cyclotronUrl
            )
            try {
                await limiter.claimUpTo(claim)
                const fault = await internalFetch(`${environment.edgeUrl()}/_faults`, {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({ name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 1 } }),
                })
                const sendBefore = await sendThrough(environment.edgeUrl())

                await environment.reset({})

                expect({
                    jobs: await jobsLeft(),
                    tokens: await limiter.claimUpTo(claim),
                    offsets: offsetsOf(),
                    sends: [fault.status, sendBefore, await sendThrough(environment.edgeUrl())],
                }).toEqual({
                    jobs: ['completed'],
                    tokens: 5,
                    offsets: everyGroupAtEnd(),
                    sends: [201, 'MessageRejected', 'sent'],
                })
            } finally {
                await forgetSesBucket(testRedis)
                await close()
            }
        }, 30_000)

        it('waits for a stopped role to leave the events group before it moves the group to the end', async () => {
            environment = environmentOf()
            await environment.up()
            holdDeadMember()

            const reset = environment.reset({}).then(
                () => 'reset',
                (error: unknown) => String(error)
            )
            const seen = await untilMemberSeen(reset)
            releaseDeadMember()

            expect({
                seen,
                reset: await reset,
                offsets: offsetsOf(),
                startedWhileMemberHeld: startedWhileMemberHeld(),
                health: await Promise.all(CdpRole.options.map((role) => healthOf(role).catch(String))),
            }).toEqual({
                seen: 'member seen',
                reset: 'reset',
                offsets: everyGroupAtEnd(),
                startedWhileMemberHeld: [],
                health: CdpRole.options.map(() => 200),
            })
        }, 45_000)

        it.each<[string, { stdout: string; stderr: string; code: number }, string | null]>([
            [
                'a topic that does not exist yet',
                {
                    stdout: '',
                    stderr: 'unable to list all offsets successfully: UNKNOWN_TOPIC_OR_PARTITION: This server does not host this topic-partition.\n',
                    code: 1,
                },
                null,
            ],
            [
                'a partition the broker refused to move',
                {
                    stdout:
                        'TOPIC                 PARTITION  PRIOR-OFFSET  CURRENT-OFFSET  ERROR\n' +
                        'scenario_seek_events  0          -1            -1              INVALID_OPERATION: seeking a non-empty group is not allowed.\n',
                    stderr: '',
                    code: 1,
                },
                'Could not move scenario-seek-group to the end of scenario_seek_events:\nscenario_seek_events/0: INVALID_OPERATION: seeking a non-empty group is not allowed.',
            ],
        ])(
            'moves the events group past %s only when rpk reports no failed partition',
            async (_name, rpkSeek, failure) => {
                writeFileSync(path.join(fakes, 'seek'), JSON.stringify(rpkSeek))
                environment = environmentOf()
                await environment.up()

                const outcome = await environment
                    .reset({
                        CDP_EVENTS_CONSUMER_GROUP_ID: 'scenario-seek-group',
                        CDP_EVENTS_CONSUMER_TOPIC: 'scenario_seek_events',
                    })
                    .then(
                        () => null,
                        (error: Error) => error.message
                    )

                expect(outcome).toEqual(failure)
            },
            30_000
        )

        it.each<[string, Role, string, () => void]>([
            [
                'loses its port to another server that answers /_health',
                'cdp-processed-events',
                'code 1',
                () => {
                    losesItsPort = 'cdp-processed-events'
                },
            ],
            [
                'cannot be spawned',
                'cdp-cyclotron-worker-email',
                'ENOENT',
                () => {
                    unspawnable = 'cdp-cyclotron-worker-email'
                },
            ],
        ])(
            'fails a reset at once naming a role that %s, why, and its log, and tears the environment down',
            async (_name, role, why, arrange) => {
                environment = environmentOf()
                await environment.up()
                const edgeUrl = environment.edgeUrl()
                arrange()

                const failure = await environment.reset({}).then(
                    () => null,
                    (error: Error) => error.message
                )

                expect(failure).toMatch(new RegExp(`^${role} `))
                expect(failure).toContain(why)
                expect(failure).toContain(logOf(role))
                const others = CdpRole.options.filter((other) => other !== role)
                expect({
                    edge: await internalFetch(`${edgeUrl}/_health`).then(
                        (answer) => answer.status,
                        () => 'unreachable'
                    ),
                    lock: await holdRunLock(path.join(process.env.XDG_CACHE_HOME!, 'posthog-scenarios')).then(
                        async (release) => {
                            await release()
                            return 'free'
                        },
                        (error: Error) => error.message
                    ),
                    rolePortsHeld: (
                        await Promise.all(
                            others.map(async (other) => ((await isPortFree(ROLE_PORTS[other])) ? [] : [other]))
                        )
                    ).flat(),
                }).toEqual({ edge: 'unreachable', lock: 'free', rolePortsHeld: [] })
            },
            30_000
        )

        it('refuses a reset when another server takes a role port while the roles are stopped', async () => {
            environment = environmentOf()
            await environment.up()
            takesPortOnExit = 'cdp-processed-events'

            await expect(environment.reset({})).rejects.toMatchObject({
                exitCode: 2,
                message: expect.stringContaining(
                    "6760 (cdp-processed-events). Find the processes that hold them with `ss -ltnp 'sport = :6760'`"
                ),
            })
        }, 30_000)

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
