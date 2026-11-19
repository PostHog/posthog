import { createHash } from 'crypto'

import { CdpRole } from '../cards'
import { TruthRecord } from '../provider-edge/truth'
import { ConsumerGroup, Role, RoleId, SCENARIO_SESSION_PREFIX } from './roles'
import { rpkOrThrow, withPostgres } from './stack'

export const TOPOLOGY_FILE = 'topology.json'

export const WORKFLOWS_ADAPTER = 'workflows'

type Partition = { topic: string; lag: number | null; client: string }

export type KafkaGroup = { group: string; partitions: Partition[] }

export type PostgresClient = { application: string; database: string; connections: number }

export type Wiring = {
    recordedAt: string
    hash: string
    processes: { adapter: string; role: Role; replicas: number }[]
    consumers: { adapter: string; role: Role; group: string; topics: string[]; lag: number | null }[]
    databases: { adapter: string; role: Role; database: string; connections: number }[]
}

export type Topology = Wiring & { hosts: { host: string; requests: number }[] }

const groupNamesOf = (rpkList: string): string[] =>
    rpkList
        .split('\n')
        .slice(1)
        .flatMap((line) => {
            const [, group] = line.trim().split(/\s+/)
            return group ? [group] : []
        })

function columnsOf(header: string): { name: string; start: number }[] {
    return [...header.matchAll(/\S+/g)].map((match) => ({ name: match[0], start: match.index }))
}

function rowsOf([header, ...rows]: string[]): Record<string, string>[] {
    const columns = columnsOf(header)
    return rows.map((row) =>
        Object.fromEntries(columns.map(({ name, start }, i) => [name, row.slice(start, columns[i + 1]?.start).trim()]))
    )
}

const numberOr = (value: string | undefined): number | null =>
    value !== undefined && /^\d+$/.test(value) ? Number(value) : null

function groupsOf(rpkDescribe: string): KafkaGroup[] {
    return rpkDescribe
        .split(/\n(?=GROUP\s)/)
        .filter((block) => /^GROUP\s/.test(block))
        .map((block) => {
            const lines = block.split('\n')
            const field = (name: string): string => new RegExp(`^${name}\\s+(.*)$`, 'm').exec(block)?.[1].trim() ?? ''
            const tableAt = lines.findIndex((line) => /^TOPIC\s+PARTITION\s/.test(line))
            const rows = tableAt < 0 ? [] : rowsOf(lines.slice(tableAt).filter((line) => line.trim() !== ''))
            const partitions = rows.map((row) => ({
                topic: row.TOPIC,
                lag: numberOr(row.LAG),
                client: row['CLIENT-ID'],
            }))
            return { group: field('GROUP'), partitions }
        })
}

const roleOfClient = (client: string): Role | undefined => {
    const role = CdpRole.safeParse(
        client.startsWith(SCENARIO_SESSION_PREFIX) ? client.slice(SCENARIO_SESSION_PREFIX.length) : ''
    )
    return role.success ? role.data : undefined
}

const topicsOf = (partitions: readonly Partition[]): string[] => [...new Set(partitions.map(({ topic }) => topic))]

export const scenarioGroupsOf = (groups: KafkaGroup[]): ConsumerGroup[] =>
    groups
        .filter(({ partitions }) => partitions.some(({ client }) => roleOfClient(client) !== undefined))
        .map(({ group, partitions }) => ({ group, topics: topicsOf(partitions) }))

export function unionOf(...lists: ConsumerGroup[][]): ConsumerGroup[] {
    const merged = new Map<string, Set<string>>()
    for (const { group, topics } of lists.flat()) {
        merged.set(group, new Set([...(merged.get(group) ?? []), ...topics]))
    }
    return [...merged].map(([group, topics]) => ({ group, topics: [...topics] }))
}

const GROUPS_PER_DESCRIBE = 20

export async function kafkaGroups(docker: string, signal?: AbortSignal): Promise<KafkaGroup[]> {
    const names = groupNamesOf(await rpkOrThrow(docker, ['group', 'list'], signal))
    const groups: KafkaGroup[] = []
    for (let at = 0; at < names.length; at += GROUPS_PER_DESCRIBE) {
        const batch = names.slice(at, at + GROUPS_PER_DESCRIBE)
        groups.push(...groupsOf(await rpkOrThrow(docker, ['group', 'describe', ...batch], signal)))
    }
    return groups
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

const hashOf = (wiring: Pick<Wiring, 'processes' | 'consumers' | 'databases'>): string =>
    createHash('sha256')
        .update(
            JSON.stringify({
                roles: wiring.processes.map(({ adapter, role }) => [adapter, role]),
                consumers: wiring.consumers.map(({ adapter, role, group, topics }) => [adapter, role, group, topics]),
                databases: [
                    ...new Set(wiring.databases.map(({ adapter, database }) => `${adapter} ${database}`)),
                ].sort(),
            })
        )
        .digest('hex')
        .slice(0, 12)

const lagOf = (partitions: readonly Partition[]): number | null =>
    partitions.some(({ lag }) => lag !== null) ? partitions.reduce((sum, { lag }) => sum + (lag ?? 0), 0) : null

function databasesOf(adapter: string, clients: readonly PostgresClient[]): Wiring['databases'] {
    const rows = new Map<string, Wiring['databases'][number]>()
    for (const { application, database, connections } of clients) {
        const role = roleOfClient(application)
        if (role) {
            const key = `${role} ${database}`
            const seen = rows.get(key)?.connections ?? 0
            rows.set(key, { adapter, role, database, connections: Math.max(seen, connections) })
        }
    }
    return [...rows.values()].sort((a, b) => `${a.role} ${a.database}`.localeCompare(`${b.role} ${b.database}`))
}

export function wiringOf(input: {
    adapter: string
    specs: readonly RoleId[]
    groups: KafkaGroup[]
    clients: PostgresClient[]
    recordedAt: Date
}): Wiring {
    const roles = [...new Set(input.specs.map(({ role }) => role))].sort()
    const { adapter } = input
    const processes = roles.map((role) => ({
        adapter,
        role,
        replicas: input.specs.filter((spec) => spec.role === role).length,
    }))
    const consumers = input.groups
        .flatMap(({ group, partitions }) =>
            [...new Set(partitions.flatMap(({ client }) => roleOfClient(client) ?? []))].map((role) => ({
                adapter,
                role,
                group,
                topics: topicsOf(partitions).sort(),
                lag: lagOf(partitions.filter(({ client }) => roleOfClient(client) === role)),
            }))
        )
        .sort((a, b) => `${a.role} ${a.group}`.localeCompare(`${b.role} ${b.group}`))
    const databases = databasesOf(adapter, input.clients)
    const wiring = { processes, consumers, databases }
    return { recordedAt: input.recordedAt.toISOString(), hash: hashOf(wiring), ...wiring }
}

export function absentGroupsOf(wiring: Wiring, expected: readonly ConsumerGroup[]): string[] {
    const joined = new Set(wiring.consumers.map(({ group }) => group))
    return expected.map(({ group }) => group).filter((group) => !joined.has(group))
}

export function nodesOf(topology: Wiring, edgeHosts: readonly string[]): string[] {
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
