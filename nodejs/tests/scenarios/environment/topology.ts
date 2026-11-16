import { createHash } from 'crypto'

import { TruthRecord } from '../provider-edge/truth'
import { ConsumerGroup, ROLE_PORTS, Role, RoleId, SCENARIO_SESSION_PREFIX } from './roles'
import { rpk, withPostgres } from './stack'

export const TOPOLOGY_FILE = 'topology.json'

// Every role the runner starts belongs to the Workflows adapter. Rows carry their adapter so another
// adapter's processes can sit beside these without sharing a role name or a hash.
export const WORKFLOWS_ADAPTER = 'workflows'

export type KafkaGroup = {
    group: string
    state: string
    topics: { topic: string; partitions: number; lag: number | null }[]
    clients: string[]
}

export type PostgresClient = { application: string; database: string; connections: number }

export type Topology = {
    recordedAt: string
    hash: string
    processes: { adapter: string; role: Role; replicas: number }[]
    consumers: { adapter: string; role: Role; group: string; topics: string[]; lag: number | null }[]
    databases: { adapter: string; role: Role; database: string; connections: number }[]
    hosts: { host: string; requests: number }[]
}

export const groupNamesOf = (rpkList: string): string[] =>
    rpkList
        .split('\n')
        .slice(1)
        .flatMap((line) => {
            const [, group] = line.trim().split(/\s+/)
            return group ? [group] : []
        })

// A partition without a member leaves only its last cells blank, so splitting on whitespace
// keeps every filled cell under its own column.
function rowsOf(table: string[]): Record<string, string>[] {
    const [header, ...rows] = table.map((line) => line.trim().split(/\s+/))
    return rows.map((cells) => Object.fromEntries(header.map((name, i) => [name, cells[i] ?? ''])))
}

const numberOr = (value: string | undefined): number | null =>
    value !== undefined && /^\d+$/.test(value) ? Number(value) : null

export function groupsOf(rpkDescribe: string): KafkaGroup[] {
    return rpkDescribe
        .split(/\n(?=GROUP\s)/)
        .filter((block) => /^GROUP\s/.test(block))
        .map((block) => {
            const lines = block.split('\n')
            const field = (name: string): string => new RegExp(`^${name}\\s+(.*)$`, 'm').exec(block)?.[1].trim() ?? ''
            const tableAt = lines.findIndex((line) => /^TOPIC\s+PARTITION\s/.test(line))
            const rows = tableAt < 0 ? [] : rowsOf(lines.slice(tableAt).filter((line) => line.trim() !== ''))
            const topics = new Map<string, { topic: string; partitions: number; lag: number | null }>()
            for (const row of rows) {
                const entry = topics.get(row.TOPIC) ?? { topic: row.TOPIC, partitions: 0, lag: null }
                const lag = numberOr(row.LAG)
                entry.partitions += 1
                entry.lag = lag === null ? entry.lag : (entry.lag ?? 0) + lag
                topics.set(row.TOPIC, entry)
            }
            const clients = [...new Set(rows.map((row) => row['CLIENT-ID']).filter((client) => client !== ''))]
            return { group: field('GROUP'), state: field('STATE'), topics: [...topics.values()], clients }
        })
}

const roleOfClient = (client: string): Role | undefined => {
    const role = client.startsWith(SCENARIO_SESSION_PREFIX) ? client.slice(SCENARIO_SESSION_PREFIX.length) : ''
    return role in ROLE_PORTS ? (role as Role) : undefined
}

// The groups the runner's own roles are members of, read from the broker rather than from config,
// so a consumer a role starts in a new mode is drained and moved to the end like the others.
export const scenarioGroupsOf = (groups: KafkaGroup[]): ConsumerGroup[] =>
    groups
        .filter(({ clients }) => clients.some((client) => roleOfClient(client) !== undefined))
        .map(({ group, topics }) => ({ group, topics: topics.map(({ topic }) => topic) }))

export function unionOf(...lists: ConsumerGroup[][]): ConsumerGroup[] {
    const merged = new Map<string, Set<string>>()
    for (const { group, topics } of lists.flat()) {
        merged.set(group, new Set([...(merged.get(group) ?? []), ...topics]))
    }
    return [...merged].map(([group, topics]) => ({ group, topics: [...topics] }))
}

export async function kafkaGroups(docker: string): Promise<KafkaGroup[]> {
    const names = groupNamesOf(await rpk(docker, ['group', 'list']))
    return names.length === 0 ? [] : groupsOf(await rpk(docker, ['group', 'describe', ...names]))
}

export async function postgresClients(postgresUrl: string): Promise<PostgresClient[]> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<PostgresClient>(
            `SELECT application_name AS application, datname AS database, count(*)::int AS connections
             FROM pg_stat_activity
             WHERE starts_with(application_name, $1) AND datname IS NOT NULL
             GROUP BY 1, 2 ORDER BY 1, 2`,
            [SCENARIO_SESSION_PREFIX]
        )
        return rows
    }, postgresUrl)
}

// The edge records the host of every webhook and answers every send as SES, which a valve names `ses`.
const hostOf = (record: TruthRecord): string | undefined =>
    record.kind === 'ses.send' ? 'ses' : record.kind === 'webhook' ? record.detail.request?.host : undefined

export function hostsOf(truth: readonly TruthRecord[]): Topology['hosts'] {
    const counts = new Map<string, number>()
    for (const record of truth) {
        const host = hostOf(record)
        if (host) {
            counts.set(host, (counts.get(host) ?? 0) + 1)
        }
    }
    return [...counts].map(([host, requests]) => ({ host, requests })).sort((a, b) => a.host.localeCompare(b.host))
}

const hashOf = (wiring: Pick<Topology, 'processes' | 'consumers' | 'databases'>): string =>
    createHash('sha256')
        .update(
            JSON.stringify({
                roles: wiring.processes.map(({ adapter, role }) => [adapter, role]),
                consumers: wiring.consumers.map(({ adapter, role, group, topics }) => [adapter, role, group, topics]),
                databases: wiring.databases.map(({ adapter, role, database }) => [adapter, role, database]),
            })
        )
        .digest('hex')
        .slice(0, 12)

// The wiring the roles showed once they were up: which process consumes which group and topic and
// talks to which database. The hash covers that wiring only, so two runs of one commit agree on it
// while lag, connection counts and the hosts a card happens to call can differ.
export function topologyOf(input: {
    adapter: string
    specs: readonly RoleId[]
    groups: KafkaGroup[]
    clients: PostgresClient[]
    recordedAt: Date
}): Topology {
    const roles = [...new Set(input.specs.map(({ role }) => role))].sort()
    const { adapter } = input
    const processes = roles.map((role) => ({
        adapter,
        role,
        replicas: input.specs.filter((spec) => spec.role === role).length,
    }))
    const consumers = input.groups
        .flatMap(({ group, topics, clients }) =>
            [...new Set(clients.flatMap((client) => roleOfClient(client) ?? []))].map((role) => ({
                adapter,
                role,
                group,
                topics: topics.map(({ topic }) => topic).sort(),
                lag: topics.some(({ lag }) => lag !== null)
                    ? topics.reduce((sum, { lag }) => sum + (lag ?? 0), 0)
                    : null,
            }))
        )
        .sort((a, b) => `${a.role} ${a.group}`.localeCompare(`${b.role} ${b.group}`))
    const databases = input.clients
        .flatMap(({ application, database, connections }) => {
            const role = roleOfClient(application)
            return role ? [{ adapter, role, database, connections }] : []
        })
        .sort((a, b) => `${a.role} ${a.database}`.localeCompare(`${b.role} ${b.database}`))
    const wiring = { processes, consumers, databases }
    return { recordedAt: input.recordedAt.toISOString(), hash: hashOf(wiring), ...wiring, hosts: [] }
}

// Valves name a role, every database the roles use as `postgres`, the job queue database as
// `cyclotron`, or a host the edge answers for.
export function nodesOf(topology: Topology, edgeHosts: readonly string[]): string[] {
    const databases = topology.databases.map(({ database }) => database)
    return [
        ...topology.processes.map(({ role }) => role),
        ...(databases.length > 0 ? ['postgres'] : []),
        ...(databases.some((database) => database.includes('cyclotron')) ? ['cyclotron'] : []),
        ...edgeHosts,
    ]
}

export function missingTargets(targets: readonly string[], nodes: readonly string[]): string[] {
    return [...new Set(targets.filter((target) => !nodes.includes(target)))]
}
