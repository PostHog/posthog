import { execFile, spawn } from 'child_process'
import { closeSync, openSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { Producer } from 'node-rdkafka'
import path from 'path'
import { Client, DatabaseError } from 'pg'
import { promisify } from 'util'

import { getDefaultConfig, overrideWithEnv } from '~/common/config/config'
import { internalFetch } from '~/common/utils/request'
import { TEST_IDS_BELOW } from '~/tests/helpers/sql'
import { PluginsServerConfig } from '~/types'

import { signal as sendSignal } from './processes'
import { ConsumerGroup, ROLE_PORTS, RoleSpec, SCENARIO_SESSION_PREFIX, SES_RATE_LIMITER_VALKEY } from './roles'

export const PROBE_TIMEOUT_MS = 2000

export const SES_RATE_LIMIT_KEY = '@posthog/ses/global'

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

const HOGLI_STOP_GRACE_MS = 5000

async function hogliExit(
    hogli: Hogli,
    args: string[],
    logFile: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<number | null> {
    signal.throwIfAborted()
    const log = openSync(logFile, 'a')
    const child = spawn(hogli.command, args, { cwd: hogli.cwd, env, stdio: ['ignore', log, log], detached: true })
    closeSync(log)
    const stopGroup = (sig: NodeJS.Signals): void => {
        if (child.pid !== undefined) {
            sendSignal(-child.pid, sig)
        }
    }
    let kill: NodeJS.Timeout | undefined
    const abort = (): void => {
        stopGroup('SIGTERM')
        kill = setTimeout(() => stopGroup('SIGKILL'), HOGLI_STOP_GRACE_MS)
    }
    signal.addEventListener('abort', abort, { once: true })
    try {
        const code = await new Promise<number | null>((resolve, reject) => {
            child.once('error', reject)
            child.once('exit', resolve)
        })
        if (signal.aborted) {
            stopGroup('SIGKILL')
            signal.throwIfAborted()
        }
        return code
    } finally {
        signal.removeEventListener('abort', abort)
        clearTimeout(kill)
    }
}

async function runHogli(
    hogli: Hogli,
    args: string[],
    logFile: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<void> {
    const code = await hogliExit(hogli, args, logFile, env, signal)
    if (code !== 0) {
        throw new Error(`hogli ${args.join(' ')} exited with ${code}; see ${logFile}`)
    }
}

const NOT_REACHABLE = 3
const FIRST_START_TIMEOUT_S = 3600

const STACK_UNITS = {
    intents: ['product_analytics', 'workflows'],
    exclude_units: ['nodejs', 'frontend', 'ingestion', 'ngrok'],
}

export async function startStack(
    hogli: Hogli,
    stateDir: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<void> {
    const config = path.join(stateDir, 'mprocs.yaml')
    const logFile = path.join(stateDir, 'hogli.log')
    const hogliEnv = { ...env, HOGLI_MPROCS_PATH: config, HOGLI_SKIP_ZOMBIE_CHECK: '1' }
    const waited = await hogliExit(hogli, ['wait'], logFile, hogliEnv, signal)
    if (waited === 0) {
        return
    }
    if (waited !== NOT_REACHABLE) {
        throw new Error(`hogli wait exited with ${waited}; see ${logFile}`)
    }
    writeFileSync(config, JSON.stringify({ _posthog: STACK_UNITS }))
    await runHogli(hogli, ['dev:generate'], logFile, hogliEnv, signal)
    await runHogli(hogli, ['up', '-d', '--custom', config], logFile, hogliEnv, signal)
    await runHogli(hogli, ['wait', '--timeout', String(FIRST_START_TIMEOUT_S)], logFile, hogliEnv, signal)
}

export async function syncTemplates(
    hogli: Hogli,
    stateDir: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<void> {
    await runHogli(hogli, ['dev:sync-hog-templates'], path.join(stateDir, 'hogli.log'), env, signal)
}

export async function withPostgres<T>(
    run: (client: Client) => Promise<T>,
    connectionString = STACK.postgresUrl,
    statementTimeoutMs = PROBE_TIMEOUT_MS
): Promise<T> {
    const client = new Client({
        connectionString,
        connectionTimeoutMillis: PROBE_TIMEOUT_MS,
        query_timeout: statementTimeoutMs,
        statement_timeout: statementTimeoutMs,
    })
    // The server can end the connection between queries, as a failover or a terminated backend does. Without
    // a listener the client throws that from an event handler and takes the process down.
    client.on('error', () => undefined)
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
                const { rows } = await client.query<{ type: string }>(
                    `SELECT DISTINCT t.typname AS type
                     FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
                     WHERE a.attrelid = ANY($1::regclass[]) AND t.typtype = 'e'
                       AND t.typnamespace = 'public'::regnamespace`,
                    [tables.map((table) => `public.${table}`)]
                )
                for (const { type } of rows) {
                    await client.query(`CREATE DOMAIN ${schema}.${type} AS public.${type}`)
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

export async function rpkOrThrow(docker: string, args: string[], signal?: AbortSignal): Promise<string> {
    const { stdout } = await promisify(execFile)(docker, ['exec', STACK.kafkaContainer, 'rpk', ...args], {
        timeout: 10_000,
        signal,
    })
    return stdout
}

export function rpk(docker: string, args: string[]): Promise<string> {
    return rpkOrThrow(docker, args).catch((error: unknown) => {
        const { stdout = '', stderr = '' } = error as { stdout?: string; stderr?: string }
        return `${stdout}${stderr}` || String(error)
    })
}

export async function groupMembers(group: string, docker: string): Promise<number> {
    const output = await rpk(docker, ['group', 'describe', group])
    const members = membersOf(output)
    if (members === null) {
        throw new Error(`Could not read the members of ${group} from rpk:\n${output}`)
    }
    return members
}

const groupOrPartitionErrored = (rpkDescribe: string): boolean =>
    /^ERROR\s/m.test(rpkDescribe) || /^TOPIC\s.*\sERROR\s*$/m.test(rpkDescribe)

export function lagOf(rpkDescribe: string): number | null {
    if (groupOrPartitionErrored(rpkDescribe)) {
        return null
    }
    const lag = /^TOTAL-LAG\s+(\d+)\s*$/m.exec(rpkDescribe)
    return lag ? Number(lag[1]) : null
}

export async function groupLag(group: string, docker: string): Promise<number> {
    const output = await rpkOrThrow(docker, ['group', 'describe', group])
    const lag = lagOf(output)
    if (lag === null) {
        throw new Error(`Could not read the lag of ${group} from rpk:\n${output}`)
    }
    return lag
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

const CREATED_OR_PRESENT = /^(OK|TOPIC_ALREADY_EXISTS\b)/

export function topicCreateFailures(rpkCreate: string): string[] {
    const [header = '', ...rows] = rpkCreate.split('\n').filter((line) => line.trim() !== '')
    if (!/^TOPIC\s+STATUS\s*$/.test(header)) {
        return [rpkCreate.trim() || 'rpk printed nothing']
    }
    return rows.flatMap((row) => {
        const [topic, ...words] = row.trim().split(/\s+/)
        const status = words.join(' ')
        return CREATED_OR_PRESENT.test(status) ? [] : [`${topic}: ${status}`]
    })
}

export async function createTopics(topics: string[], docker: string): Promise<void> {
    if (topics.length === 0) {
        return
    }
    const failures = topicCreateFailures(await rpk(docker, ['topic', 'create', '--', ...topics]))
    if (failures.length > 0) {
        throw new Error(`Could not create the Kafka topics the roles read:\n${failures.join('\n')}`)
    }
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

const settingsOf = (spec: RoleSpec): PluginsServerConfig =>
    overrideWithEnv({ ...getDefaultConfig(), DATABASE_URL: STACK.postgresUrl }, spec.env)

export const postgresUrlOf = (spec: RoleSpec): string => settingsOf(spec).DATABASE_URL

const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '[::1]']
const POSTGRES_URL = /^postgres(ql)?:\/\//

function serverOf(url: string): string {
    const { hostname, port } = new URL(url)
    return `${LOOPBACK_HOSTS.includes(hostname) ? 'localhost' : hostname}:${port || '5432'}`
}

export function postgresServersOf(spec: RoleSpec, postgresUrl: string): string[] {
    const urls = [
        postgresUrl,
        ...Object.values(settingsOf(spec)).filter(
            (value): value is string => typeof value === 'string' && POSTGRES_URL.test(value)
        ),
    ]
    return urls.filter((url, i) => urls.findIndex((other) => serverOf(other) === serverOf(url)) === i)
}

export const RESIDENT_TEAMS_FROM = TEST_IDS_BELOW

export async function deleteUnfinishedJobs(cyclotronUrl: string): Promise<void> {
    await withPostgres(
        (client) =>
            client.query("DELETE FROM cyclotron_jobs WHERE status IN ('available', 'running') AND team_id < $1", [
                RESIDENT_TEAMS_FROM,
            ]),
        cyclotronUrl
    )
}

export type Sessions = { names: string[]; prefix: string }

const ROLE_SESSIONS: Sessions = { names: Object.keys(ROLE_PORTS), prefix: SCENARIO_SESSION_PREFIX }

export async function terminateRoleConnections(
    postgresUrl: string,
    share: number,
    { names, prefix }: Sessions = ROLE_SESSIONS
): Promise<number> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<{ pid: number }>(
            `SELECT pid FROM pg_stat_activity
             WHERE pid <> pg_backend_pid() AND (application_name = ANY($1) OR starts_with(application_name, $2))
             ORDER BY random()`,
            [names, prefix]
        )
        const chosen = rows.slice(0, Math.ceil(share * rows.length)).map(({ pid }) => pid)
        const terminated = await client.query<{ terminated: number }>(
            'SELECT count(*) FILTER (WHERE pg_terminate_backend(pid))::int AS terminated FROM unnest($1::int[]) AS pid',
            [chosen]
        )
        return terminated.rows[0].terminated
    }, postgresUrl)
}

export async function rolesNotReady(specs: RoleSpec[]): Promise<RoleSpec[]> {
    const results = await Promise.all(
        specs.map((spec) =>
            expectOk(`http://127.0.0.1:${spec.port}/_health`).then(
                () => null,
                () => spec
            )
        )
    )
    return results.filter((spec): spec is RoleSpec => spec !== null)
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

class HttpAnswer extends Error {}

export async function expectOk(url: string): Promise<void> {
    const { status } = await internalFetch(url, { timeoutMs: PROBE_TIMEOUT_MS })
    if (status !== 200) {
        throw new HttpAnswer(`${url} answered ${status}`)
    }
}

export type ProbeFailure = {
    name: string
    reason: string
    unanswered: boolean
    hostLimit?: string
    sockets?: Record<string, number>
}

export type Probes = Record<string, () => Promise<unknown>>

export function dependencyProbes(
    edgeUrl: string | undefined,
    postgresUrl: string,
    sesValkey: { host: string; port: number }
): Probes {
    return {
        postgres: () => withPostgres((client) => client.query('SELECT 1'), postgresUrl),
        kafka: pingKafka,
        redis: () => pingRedis(STACK.redis),
        'ses-rate-limiter-valkey': () => pingRedis(sesValkey),
        personhog: () => expectOk(STACK.personhogReadinessUrl),
        'provider-edge': () => (edgeUrl ? expectOk(`${edgeUrl}/_health`) : Promise.reject(new Error('not started'))),
    }
}

const ANSWER_CODES = new Set(['ECONNREFUSED', 'ECONNRESET', 'ENOTFOUND', 'EHOSTUNREACH'])

const HOST_LIMITS: Record<string, string> = {
    EADDRNOTAVAIL: 'local ports',
    EMFILE: 'file descriptors',
    ENFILE: 'file descriptors',
}

const TIMER_SLACK_MS = 10

const SOCKET_GROUPS_KEPT = 20

// A host out of local ports lists tens of thousands of sockets, which is past execFile's 1 MiB default.
const SOCKET_LISTING_MAX_BYTES = 64 * 1024 * 1024

// What held the host's ports is gone once the run ends, so the check keeps the busiest TCP states and peers.
async function socketsOf(): Promise<Record<string, number> | undefined> {
    try {
        const { stdout } = await promisify(execFile)('ss', ['-tanH'], {
            timeout: PROBE_TIMEOUT_MS,
            maxBuffer: SOCKET_LISTING_MAX_BYTES,
        })
        const counts = new Map<string, number>()
        for (const line of stdout.split('\n')) {
            const [state, , , , peer] = line.trim().split(/\s+/)
            if (peer !== undefined) {
                counts.set(`${state} ${peer}`, (counts.get(`${state} ${peer}`) ?? 0) + 1)
            }
        }
        return Object.fromEntries([...counts].sort(([, a], [, b]) => b - a).slice(0, SOCKET_GROUPS_KEPT))
    } catch {
        return undefined
    }
}

const codeOf = (error: unknown): unknown =>
    typeof error === 'object' && error !== null && 'code' in error ? error.code : undefined

const isTypedAnswer = (error: unknown): boolean =>
    error instanceof HttpAnswer || error instanceof DatabaseError || ANSWER_CODES.has(String(codeOf(error)))

const isAnswer = (error: unknown): boolean =>
    isTypedAnswer(error) || (error instanceof Error && isTypedAnswer(error.cause))

export const hostLimitOf = (error: unknown): string | undefined =>
    HOST_LIMITS[String(codeOf(error))] ??
    (error instanceof Error ? HOST_LIMITS[String(codeOf(error.cause))] : undefined)

export async function failedProbes(probes: Probes): Promise<ProbeFailure[]> {
    const results = await Promise.all(
        Object.entries(probes).map(async ([name, probe]): Promise<ProbeFailure | null> => {
            const startedAt = performance.now()
            try {
                await probe()
                return null
            } catch (error) {
                const ranOutItsClock = performance.now() - startedAt >= PROBE_TIMEOUT_MS - TIMER_SLACK_MS
                const reason = error instanceof Error ? error.message : String(error)
                const hostLimit = hostLimitOf(error)
                const sockets = hostLimit ? await socketsOf() : undefined
                return {
                    name,
                    reason,
                    unanswered: ranOutItsClock && !isAnswer(error),
                    ...(hostLimit ? { hostLimit } : {}),
                    ...(sockets ? { sockets } : {}),
                }
            }
        })
    )
    return results.filter((failure): failure is ProbeFailure => failure !== null)
}
