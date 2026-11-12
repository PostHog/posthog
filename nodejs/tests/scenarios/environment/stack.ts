import { execFile, spawn } from 'child_process'
import { closeSync, openSync } from 'fs'
import Redis from 'ioredis'
import { Producer } from 'node-rdkafka'
import path from 'path'
import { Client } from 'pg'
import { promisify } from 'util'

import { SES_RATE_LIMIT_KEY } from '~/cdp/services/job-queue/job-queue-rate-limited-postgres-v2'
import { internalFetch } from '~/common/utils/request'

import { ConsumerGroup, ROLE_PORTS, Role, RoleSpec, SES_RATE_LIMITER_VALKEY } from './roles'

const PROBE_TIMEOUT_MS = 2000

export const STACK = {
    postgresUrl: 'postgres://posthog:posthog@localhost:5432/posthog',
    cyclotronNodeUrl: 'postgres://posthog:posthog@localhost:5432/cyclotron_node',
    kafkaHosts: 'kafka:9092',
    redis: { host: '127.0.0.1', port: 6379 },
    sesRateLimiterValkey: SES_RATE_LIMITER_VALKEY,
    personhogReadinessUrl: 'http://127.0.0.1:9101/_readiness',
    kafkaContainer: 'posthog-kafka-1',
    templates: ['template-email', 'template-webhook'],
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

export async function startStack(hogli: Hogli, stateDir: string, env: NodeJS.ProcessEnv): Promise<void> {
    const config = path.join(stateDir, 'mprocs.yaml')
    const logFile = path.join(stateDir, 'hogli.log')
    const hogliEnv = { ...env, HOGLI_MPROCS_PATH: config, HOGLI_SKIP_ZOMBIE_CHECK: '1' }
    const waited = await hogliExit(hogli, ['wait'], logFile, hogliEnv)
    if (waited === 0) {
        return
    }
    if (waited !== NOT_REACHABLE) {
        throw new Error(`hogli wait exited with ${waited}; see ${logFile}`)
    }
    await runHogli(hogli, ['dev:generate', '--with', 'workflows', '--without', 'nodejs'], logFile, hogliEnv)
    await runHogli(hogli, ['up', '-d', '--custom', config], logFile, hogliEnv)
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

export type ScratchSchema = { url: string; create(): Promise<void>; drop(): Promise<void> }

export function scratchSchema(connectionString: string, schema: string, tables: string[]): ScratchSchema {
    const searchPath = encodeURIComponent(`-c search_path=${schema}`)
    return {
        url: `${connectionString}${connectionString.includes('?') ? '&' : '?'}options=${searchPath}`,
        create: () =>
            withPostgres(async (client) => {
                await client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`)
                await client.query(`CREATE SCHEMA ${schema}`)
                for (const table of tables) {
                    await client.query(`CREATE TABLE ${schema}.${table} (LIKE public.${table} INCLUDING ALL)`)
                }
            }, connectionString),
        drop: async () => {
            await withPostgres((client) => client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`), connectionString)
        },
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

async function rpk(docker: string, args: string[]): Promise<string> {
    try {
        const { stdout } = await promisify(execFile)(docker, ['exec', STACK.kafkaContainer, 'rpk', ...args], {
            timeout: 10_000,
        })
        return stdout
    } catch (error) {
        const { stdout = '', stderr = '' } = error as { stdout?: string; stderr?: string }
        return `${stdout}${stderr}` || String(error)
    }
}

export async function groupMembers(group: string, docker: string): Promise<number> {
    const output = await rpk(docker, ['group', 'describe', group])
    const members = membersOf(output)
    if (members === null) {
        throw new Error(`Could not read the members of ${group} from rpk:\n${output}`)
    }
    return members
}

export function seekFailures(rpkSeek: string): string[] {
    const lines = rpkSeek.split('\n').filter((line) => line.trim() !== '')
    const header = lines[0] ?? ''
    if (/UNKNOWN_TOPIC_OR_PARTITION/.test(header)) {
        return []
    }
    if (!/^TOPIC\s+PARTITION\s/.test(header)) {
        return [rpkSeek.trim() || 'rpk printed nothing']
    }
    const errorAt = header.indexOf('ERROR')
    if (errorAt < 0) {
        return []
    }
    return lines.slice(1).flatMap((row) => {
        const error = row.slice(errorAt).trim()
        const [topic, partition] = row.trim().split(/\s+/)
        return error ? [`${topic}/${partition}: ${error}`] : []
    })
}

export async function seekToEnd({ group, topics }: ConsumerGroup, docker: string): Promise<void> {
    for (const topic of topics) {
        const output = await rpk(docker, [
            'group',
            'seek',
            group,
            '--to',
            'end',
            '--topics',
            topic,
            '--allow-new-topics',
        ])
        const failures = seekFailures(output)
        if (failures.length > 0) {
            throw new Error(`Could not move ${group} to the end of ${topic}:\n${failures.join('\n')}`)
        }
    }
}

export const cyclotronUrlOf = (spec: RoleSpec): string => spec.env.CYCLOTRON_NODE_DATABASE_URL || STACK.cyclotronNodeUrl

const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '[::1]']

function serverOf(url: string): string {
    const { hostname, port } = new URL(url)
    return `${LOOPBACK_HOSTS.includes(hostname) ? 'localhost' : hostname}:${port || '5432'}`
}

export function postgresServersOf(spec: RoleSpec, postgresUrl: string): string[] {
    const urls = [postgresUrl, ...Object.values(spec.env).filter((url): url is string => !!url?.startsWith('postgres'))]
    return urls.filter((url, i) => urls.findIndex((other) => serverOf(other) === serverOf(url)) === i)
}

export async function deleteUnfinishedJobs(cyclotronUrl: string): Promise<void> {
    await withPostgres(
        (client) => client.query("DELETE FROM cyclotron_jobs WHERE status IN ('available', 'running')"),
        cyclotronUrl
    )
}

export async function terminateRoleConnections(postgresUrl: string, share: number): Promise<number> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<{ pid: number }>(
            `SELECT pid FROM pg_stat_activity
             WHERE pid <> pg_backend_pid() AND (application_name = ANY($1) OR application_name LIKE 'scenario-%')
             ORDER BY random()`,
            [Object.keys(ROLE_PORTS)]
        )
        const chosen = rows.slice(0, Math.ceil(share * rows.length)).map(({ pid }) => pid)
        const terminated = await client.query<{ terminated: number }>(
            'SELECT count(*) FILTER (WHERE pg_terminate_backend(pid))::int AS terminated FROM unnest($1::int[]) AS pid',
            [chosen]
        )
        return terminated.rows[0].terminated
    }, postgresUrl)
}

export async function rolesNotReady(specs: RoleSpec[]): Promise<Role[]> {
    const results = await Promise.all(
        specs.map(({ role }) =>
            expectOk(`http://127.0.0.1:${ROLE_PORTS[role]}/_health`).then(
                () => null,
                () => role
            )
        )
    )
    return results.filter((role): role is Role => role !== null)
}

export async function forgetSesBucket({ host, port }: { host: string; port: number }): Promise<void> {
    const valkey = new Redis({
        host,
        port,
        lazyConnect: true,
        commandTimeout: PROBE_TIMEOUT_MS,
        maxRetriesPerRequest: 0,
    })
    try {
        await valkey.connect()
        await valkey.del(SES_RATE_LIMIT_KEY)
    } finally {
        valkey.disconnect()
    }
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

export async function downServices(
    edgeUrl: string | undefined,
    postgresUrl: string,
    sesValkey: { host: string; port: number }
): Promise<string[]> {
    const probes: Record<string, () => Promise<unknown>> = {
        postgres: () => withPostgres((client) => client.query('SELECT 1'), postgresUrl),
        kafka: pingKafka,
        redis: () => pingRedis(STACK.redis),
        'ses-rate-limiter-valkey': () => pingRedis(sesValkey),
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
