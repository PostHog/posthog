import { execFile, spawn } from 'child_process'
import { closeSync, openSync } from 'fs'
import Redis from 'ioredis'
import { Producer } from 'node-rdkafka'
import path from 'path'
import { Client } from 'pg'
import { promisify } from 'util'

import { getDefaultCdpConfig } from '~/cdp/config'
import { internalFetch } from '~/common/utils/request'

import { RoleSpec } from './roles'

const PROBE_TIMEOUT_MS = 2000

export const STACK = {
    postgresUrl: 'postgres://posthog:posthog@localhost:5432/posthog',
    kafkaHosts: 'kafka:9092',
    redis: { host: '127.0.0.1', port: 6379 },
    sesRateLimiterValkey: { host: '127.0.0.1', port: 6390 },
    personhogReadinessUrl: 'http://127.0.0.1:9101/_readiness',
    kafkaContainer: 'posthog-kafka-1',
    templates: ['template-email', 'template-webhook'],
}

export function eventsConsumerGroup(specs: RoleSpec[]): string {
    const events = specs.find((spec) => spec.role === 'cdp-processed-events')
    return events?.env.CDP_EVENTS_CONSUMER_GROUP_ID || getDefaultCdpConfig().CDP_EVENTS_CONSUMER_GROUP_ID
}

export type Hogli = { command: string; cwd: string }

async function hogliExit(
    hogli: Hogli,
    args: string[],
    logFile: string,
    env: NodeJS.ProcessEnv
): Promise<number | null> {
    const log = openSync(logFile, 'a')
    const child = spawn(hogli.command, args, { cwd: hogli.cwd, env, stdio: ['ignore', log, log] })
    closeSync(log)
    return await new Promise<number | null>((resolve, reject) => {
        child.once('error', reject)
        child.once('exit', resolve)
    })
}

async function runHogli(hogli: Hogli, args: string[], logFile: string, env: NodeJS.ProcessEnv): Promise<void> {
    const code = await hogliExit(hogli, args, logFile, env)
    if (code !== 0) {
        throw new Error(`hogli ${args.join(' ')} exited with ${code}; see ${logFile}`)
    }
}

const NOT_REACHABLE = 3
const PHROCS_SOCKET_GRACE_S = 30

export async function startStack(hogli: Hogli, stateDir: string, env: NodeJS.ProcessEnv): Promise<void> {
    const config = path.join(stateDir, 'mprocs.yaml')
    const logFile = path.join(stateDir, 'hogli.log')
    const hogliEnv = { ...env, HOGLI_MPROCS_PATH: config, HOGLI_SKIP_ZOMBIE_CHECK: '1' }
    if (
        (await hogliExit(hogli, ['wait', '--timeout', String(PHROCS_SOCKET_GRACE_S + 1)], logFile, hogliEnv)) ===
        NOT_REACHABLE
    ) {
        await runHogli(hogli, ['dev:generate', '--with', 'workflows', '--without', 'nodejs'], logFile, hogliEnv)
        await runHogli(hogli, ['up', '-d', '--custom', config], logFile, hogliEnv)
    }
    await runHogli(hogli, ['wait'], logFile, hogliEnv)
}

export async function syncTemplates(hogli: Hogli, stateDir: string, env: NodeJS.ProcessEnv): Promise<void> {
    await runHogli(hogli, ['dev:sync-hog-templates'], path.join(stateDir, 'hogli.log'), env)
}

export async function withPostgres<T>(
    run: (client: Client) => Promise<T>,
    connectionString = STACK.postgresUrl
): Promise<T> {
    const client = new Client({
        connectionString,
        connectionTimeoutMillis: PROBE_TIMEOUT_MS,
        query_timeout: PROBE_TIMEOUT_MS,
        statement_timeout: PROBE_TIMEOUT_MS,
    })
    try {
        await client.connect()
        return await run(client)
    } catch (error) {
        throw new Error(`Postgres at ${new URL(connectionString).host} failed: ${(error as Error).message}`, {
            cause: error,
        })
    } finally {
        await client.end().catch(() => undefined)
    }
}

export async function missingTemplates(postgresUrl: string): Promise<string[]> {
    const present = await withPostgres(async (client) => {
        const { rows } = await client.query<{ template_id: string }>(
            'SELECT DISTINCT template_id FROM posthog_hogfunctiontemplate WHERE template_id = ANY($1)',
            [STACK.templates]
        )
        return rows.map((row) => row.template_id)
    }, postgresUrl)
    return STACK.templates.filter((template) => !present.includes(template))
}

export function membersOf(rpkDescribe: string): number | null {
    const members = /^MEMBERS\s+(\d+)\s*$/m.exec(rpkDescribe)
    return members ? Number(members[1]) : null
}

export async function groupMembers(group: string, docker: string): Promise<number> {
    const { stdout } = await promisify(execFile)(
        docker,
        ['exec', STACK.kafkaContainer, 'rpk', 'group', 'describe', group],
        { timeout: 10_000 }
    )
    const members = membersOf(stdout)
    if (members === null) {
        throw new Error(`Could not read the members of ${group} from rpk:\n${stdout}`)
    }
    return members
}

export async function pingRedis({ host, port }: { host: string; port: number }): Promise<void> {
    const redis = new Redis({
        host,
        port,
        lazyConnect: true,
        connectTimeout: PROBE_TIMEOUT_MS,
        commandTimeout: PROBE_TIMEOUT_MS,
        enableReadyCheck: false,
        maxRetriesPerRequest: 0,
        enableOfflineQueue: false,
        retryStrategy: () => null,
    })
    try {
        await redis.connect()
        await redis.ping()
    } finally {
        redis.disconnect()
    }
}

async function pingKafka(): Promise<void> {
    const producer = new Producer({ 'metadata.broker.list': STACK.kafkaHosts })
    await new Promise<void>((resolve, reject) =>
        producer.connect({ timeout: PROBE_TIMEOUT_MS }, (error) => (error ? reject(error) : resolve()))
    )
    await new Promise((resolve) => producer.disconnect(resolve))
}

export async function expectOk(url: string): Promise<void> {
    const { status } = await internalFetch(url, { timeoutMs: PROBE_TIMEOUT_MS })
    if (status !== 200) {
        throw new Error(`${url} answered ${status}`)
    }
}

export async function downServices(edgeUrl: string | undefined, postgresUrl: string): Promise<string[]> {
    const probes: Record<string, () => Promise<unknown>> = {
        postgres: () => withPostgres((client) => client.query('SELECT 1'), postgresUrl),
        kafka: pingKafka,
        redis: () => pingRedis(STACK.redis),
        'ses-rate-limiter-valkey': () => pingRedis(STACK.sesRateLimiterValkey),
        personhog: () => expectOk(STACK.personhogReadinessUrl),
        'provider-edge': () => (edgeUrl ? expectOk(`${edgeUrl}/_health`) : Promise.reject(new Error('not started'))),
    }
    const results = await Promise.all(
        Object.entries(probes).map(([name, probe]) =>
            probe().then(
                () => null,
                () => name
            )
        )
    )
    return results.filter((name): name is string => name !== null)
}
