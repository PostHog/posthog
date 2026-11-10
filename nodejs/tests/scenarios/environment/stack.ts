import { execFile, spawn } from 'child_process'
import { closeSync, openSync } from 'fs'
import Redis from 'ioredis'
import path from 'path'
import { Client } from 'pg'
import { setTimeout as sleep } from 'timers/promises'
import { promisify } from 'util'

import { getDefaultCdpConfig } from '~/cdp/config'
import { internalFetch } from '~/common/utils/request'

import { ConsumerGroup, Role, RoleSpec } from './roles'

const PROBE_TIMEOUT_MS = 2000

export const STACK = {
    postgresUrl: 'postgres://posthog:posthog@localhost:5432/posthog',
    cyclotronNodeUrl: 'postgres://posthog:posthog@localhost:5432/cyclotron_node',
    kafkaHosts: 'kafka:9092',
    redis: { host: '127.0.0.1', port: 6379 },
    sesRateLimiterValkey: { host: '127.0.0.1', port: 6390 },
    personhogReadinessUrl: 'http://127.0.0.1:9101/_readiness',
    kafkaContainer: 'posthog-kafka-1',
    eventsConsumerGroup: getDefaultCdpConfig().CDP_EVENTS_CONSUMER_GROUP_ID,
    templates: ['template-email', 'template-webhook'],
}

export async function poll<T>(probe: () => Promise<T | undefined>, timeoutMs: number): Promise<T | undefined> {
    const deadline = Date.now() + timeoutMs
    for (;;) {
        const found = await probe()
        if (found !== undefined || Date.now() >= deadline) {
            return found
        }
        await sleep(1000)
    }
}

async function hogli(repoRoot: string, args: string[], logFile: string, env: NodeJS.ProcessEnv): Promise<void> {
    const log = openSync(logFile, 'a')
    const child = spawn(`${repoRoot}/bin/hogli`, args, { cwd: repoRoot, env, stdio: ['ignore', log, log] })
    closeSync(log)
    const code = await new Promise<number | null>((resolve, reject) => {
        child.once('error', reject)
        child.once('exit', resolve)
    })
    if (code !== 0) {
        throw new Error(`hogli ${args.join(' ')} exited with ${code}; see ${logFile}`)
    }
}

export async function startStack(repoRoot: string, stateDir: string, env: NodeJS.ProcessEnv): Promise<void> {
    const config = path.join(stateDir, 'mprocs.yaml')
    const logFile = path.join(stateDir, 'hogli.log')
    const hogliEnv = { ...env, HOGLI_MPROCS_PATH: config, HOGLI_SKIP_ZOMBIE_CHECK: '1' }
    await hogli(repoRoot, ['dev:generate', '--with', 'workflows', '--without', 'nodejs'], logFile, hogliEnv)
    await hogli(repoRoot, ['up', '-d', '--custom', config], logFile, hogliEnv)
    await hogli(repoRoot, ['wait'], logFile, hogliEnv)
}

export async function withPostgres<T>(
    run: (client: Client) => Promise<T>,
    connectionString = STACK.postgresUrl
): Promise<T> {
    const client = new Client({ connectionString, connectionTimeoutMillis: PROBE_TIMEOUT_MS })
    try {
        await client.connect()
        return await run(client)
    } finally {
        await client.end().catch(() => undefined)
    }
}

export async function missingTemplates(): Promise<string[]> {
    const present = await withPostgres(async (client) => {
        const { rows } = await client.query<{ template_id: string }>(
            'SELECT DISTINCT template_id FROM posthog_hogfunctiontemplate WHERE template_id = ANY($1)',
            [STACK.templates]
        )
        return rows.map((row) => row.template_id)
    }).catch((): string[] => [])
    return STACK.templates.filter((template) => !present.includes(template))
}

export function membersOf(rpkDescribe: string): number | null {
    const members = /^MEMBERS\s+(\d+)\s*$/m.exec(rpkDescribe)
    if (members) {
        return Number(members[1])
    }
    return /GROUP_ID_NOT_FOUND/.test(rpkDescribe) ? 0 : null
}

async function rpk(args: string[]): Promise<string> {
    try {
        const { stdout } = await promisify(execFile)('docker', ['exec', STACK.kafkaContainer, 'rpk', ...args], {
            timeout: 10_000,
        })
        return stdout
    } catch (error) {
        const { stdout = '', stderr = '' } = error as { stdout?: string; stderr?: string }
        return `${stdout}${stderr}` || String(error)
    }
}

export async function groupMembers(group: string): Promise<number> {
    const output = await rpk(['group', 'describe', group])
    const members = membersOf(output)
    if (members === null) {
        throw new Error(`Could not read the members of ${group} from rpk:\n${output}`)
    }
    return members
}

export function seekFailures(rpkSeek: string): string[] {
    const lines = rpkSeek.split('\n').filter((line) => line.trim() !== '')
    const header = lines[0] ?? ''
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

export async function seekToEnd({ group, topics }: ConsumerGroup): Promise<void> {
    const failures = seekFailures(
        await rpk(['group', 'seek', group, '--to', 'end', '--topics', topics.join(','), '--allow-new-topics'])
    )
    if (failures.length > 0) {
        throw new Error(`Could not move ${group} to the end of ${topics.join(', ')}:\n${failures.join('\n')}`)
    }
}

export const cyclotronUrlOf = (spec: RoleSpec): string => spec.env.CYCLOTRON_NODE_DATABASE_URL || STACK.cyclotronNodeUrl

export async function deleteUnfinishedJobs(cyclotronUrl: string): Promise<void> {
    await withPostgres(
        (client) => client.query("DELETE FROM cyclotron_jobs WHERE status IN ('available', 'running')"),
        cyclotronUrl
    )
}

export async function rolesNotReady(specs: RoleSpec[]): Promise<Role[]> {
    const results = await Promise.all(
        specs.map(({ role, port }) =>
            expectOk(`http://127.0.0.1:${port}/_health`).then(
                () => null,
                () => role
            )
        )
    )
    return results.filter((role): role is Role => role !== null)
}

async function pingRedis({ host, port }: { host: string; port: number }): Promise<void> {
    const redis = new Redis({
        host,
        port,
        lazyConnect: true,
        connectTimeout: PROBE_TIMEOUT_MS,
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
    const { Producer } = await import('node-rdkafka')
    const producer = new Producer({ 'metadata.broker.list': STACK.kafkaHosts })
    await new Promise<void>((resolve, reject) =>
        producer.connect({ timeout: PROBE_TIMEOUT_MS }, (error) => (error ? reject(error) : resolve()))
    )
    await new Promise((resolve) => producer.disconnect(resolve))
}

async function expectOk(url: string): Promise<void> {
    const { status } = await internalFetch(url, { timeoutMs: PROBE_TIMEOUT_MS })
    if (status !== 200) {
        throw new Error(`${url} answered ${status}`)
    }
}

export async function downServices(edgeUrl: string | undefined): Promise<string[]> {
    const probes: Record<string, () => Promise<unknown>> = {
        postgres: () => withPostgres((client) => client.query('SELECT 1')),
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
