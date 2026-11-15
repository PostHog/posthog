import { Client } from 'pg'
import { setTimeout as sleep } from 'timers/promises'

import { Aws, AwsError } from '../cloud/aws'
import type { Manifest } from '../cloud/lease'
import { RUN_TAG } from '../cloud/stack'
import type { WriterSample } from '../probe/writer-probe'
import { SCENARIO_SESSION_PREFIX } from './roles'

export type ObservationName = 'cluster_writer' | 'sql_writer' | 'first_probe_commit'

export type Observation = { name: ObservationName; at: string }

export type FailoverJournal = {
    intentAt?: string
    observations?: Observation[]
    releaseIntentAt?: string
    releaseObservations?: Observation[]
    releaseError?: string
    unobserved?: string
}

export type SqlIdentity = { instance: string; inRecovery: boolean }

export type FailoverActuation = {
    observed(signal?: AbortSignal): Promise<boolean>
    release(): Promise<void>
    journal(): FailoverJournal
}

export type FailoverOptions = {
    aws: Aws
    manifest: Manifest
    holdMs: number
    identity(): Promise<SqlIdentity>
    commits(): readonly WriterSample[]
    now?: () => number
    pollMs?: number
    observeWithinMs?: number
}

const POLL_MS = 1000
const OBSERVE_WITHIN_MS = 5 * 60_000
const MINUTE_MS = 60_000
const CAPACITY_MINUTES = 5
const CAPACITY_FRESH_WITHIN_MS = 3 * MINUTE_MS
const IDLE_ACU = 1
const IDENTITY_TIMEOUT_MS = 2000
const OBSERVATIONS: ObservationName[] = ['cluster_writer', 'sql_writer', 'first_probe_commit']

type Cluster = {
    Status: string
    TagList?: { Key: string; Value: string }[]
    DBClusterMembers?: { DBInstanceIdentifier: string; IsClusterWriter: boolean }[]
}

type CapacityData = { MetricDataResults: { Timestamps: string[]; Values: number[] }[] }

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

export async function sqlIdentityOf(url: string): Promise<SqlIdentity> {
    const client = new Client({
        connectionString: url,
        application_name: `${SCENARIO_SESSION_PREFIX}failover`,
        connectionTimeoutMillis: IDENTITY_TIMEOUT_MS,
        statement_timeout: IDENTITY_TIMEOUT_MS,
        query_timeout: IDENTITY_TIMEOUT_MS,
    })
    client.on('error', () => undefined)
    try {
        await client.connect()
        const { rows } = await client.query<{ instance: string; in_recovery: boolean }>(
            'SELECT aurora_db_instance_identifier() AS instance, pg_is_in_recovery() AS in_recovery'
        )
        return { instance: rows[0].instance, inRecovery: rows[0].in_recovery }
    } finally {
        await client.end().catch(() => undefined)
    }
}

export async function failOver({
    aws,
    manifest,
    holdMs,
    identity,
    commits,
    now = Date.now,
    pollMs = POLL_MS,
    observeWithinMs = OBSERVE_WITHIN_MS,
}: FailoverOptions): Promise<FailoverActuation> {
    const cluster = manifest.stackName
    const writer = `${cluster}-writer`
    const reader = `${cluster}-reader`
    const journal: FailoverJournal = {}
    const refuse = (reason: string): never => {
        throw new Error(`pg.failover refused: ${reason}`)
    }

    const describe = async (): Promise<Cluster> =>
        (
            (await aws.call(['rds', 'describe-db-clusters', '--db-cluster-identifier', cluster])) as {
                DBClusters: Cluster[]
            }
        ).DBClusters[0]
    const writerOf = (described: Cluster): string | undefined =>
        described.DBClusterMembers?.find(({ IsClusterWriter }) => IsClusterWriter)?.DBInstanceIdentifier

    const { Account } = (await aws.call(['sts', 'get-caller-identity'])) as { Account: string }
    if (Account !== manifest.account) {
        refuse(`the caller is in account ${Account}, not the run's account ${manifest.account}`)
    }
    const leaseLeftMs = Date.parse(manifest.expiresAt) - now()
    if (leaseLeftMs < holdMs + observeWithinMs) {
        refuse(
            `the lease has ${Math.floor(leaseLeftMs / 1000)}s left, under the ${(holdMs + observeWithinMs) / 1000}s the hold and fail-back need`
        )
    }
    const described = await describe()
    const tagged = described.TagList?.some(({ Key, Value }) => Key === RUN_TAG && Value === manifest.runId)
    const members = (described.DBClusterMembers ?? []).map(({ DBInstanceIdentifier }) => DBInstanceIdentifier).sort()
    if (!tagged) {
        refuse(`${cluster} does not carry ${RUN_TAG}=${manifest.runId}`)
    }
    if (described.Status !== 'available') {
        refuse(`${cluster} is ${described.Status}, not available`)
    }
    if (members.join(',') !== [reader, writer].sort().join(',') || writerOf(described) !== writer) {
        refuse(
            `${cluster} has members ${members.join(', ') || 'none'} with writer ${writerOf(described)}, not ${writer} writing beside ${reader}`
        )
    }
    await requireIdleReader()

    const promote = async (to: string): Promise<{ intentAt: string; ambiguous?: string; refused?: string }> => {
        const intentAt = new Date(now()).toISOString()
        try {
            await aws.call([
                'rds',
                'failover-db-cluster',
                '--db-cluster-identifier',
                cluster,
                '--target-db-instance-identifier',
                to,
            ])
            return { intentAt }
        } catch (error) {
            return error instanceof AwsError && error.code !== undefined
                ? { intentAt, refused: messageOf(error) }
                : { intentAt, ambiguous: messageOf(error) }
        }
    }

    const observe = async (
        to: string,
        intentAt: string,
        into: Observation[],
        signal: AbortSignal
    ): Promise<boolean> => {
        const since = Date.parse(intentAt)
        const seen = (name: ObservationName): boolean => into.some((observation) => observation.name === name)
        const record = (name: ObservationName, at: number): void => {
            if (!seen(name)) {
                into.push({ name, at: new Date(at).toISOString() })
            }
        }
        for (;;) {
            if (!seen('cluster_writer')) {
                const at = now()
                const current = await describe().catch(() => undefined)
                if (current && writerOf(current) === to) {
                    record('cluster_writer', at)
                }
            }
            if (!seen('sql_writer')) {
                const at = now()
                const sql = await identity().catch(() => undefined)
                if (sql?.instance === to && !sql.inRecovery) {
                    record('sql_writer', at)
                }
            }
            if (!seen('first_probe_commit')) {
                const commit = commits().find(
                    (sample) => sample.ok && sample.instance === to && sample.at + sample.latencyMs >= since
                )
                if (commit) {
                    record('first_probe_commit', commit.at + commit.latencyMs)
                }
            }
            if (OBSERVATIONS.every(seen)) {
                return true
            }
            if (signal.aborted) {
                return false
            }
            await sleep(pollMs, undefined, { signal }).catch(() => undefined)
        }
    }

    const unobservedOf = (
        what: string,
        to: string,
        into: Observation[],
        { ambiguous, refused }: { ambiguous?: string; refused?: string }
    ): string => {
        if (refused !== undefined) {
            return `the ${what} request was refused: ${refused}`
        }
        const missing = OBSERVATIONS.filter((name) => !into.some((observation) => observation.name === name))
        return ambiguous !== undefined && missing.includes('cluster_writer')
            ? `${what} request ambiguous, not observed: ${ambiguous}`
            : `${to} did not show ${missing.join(', ')} within ${observeWithinMs / 1000}s of the ${what} intent`
    }

    const promoted = await promote(reader)
    journal.intentAt = promoted.intentAt
    journal.observations = []
    let observing: Promise<boolean> | undefined
    let released: Promise<void> | undefined

    return {
        observed: (signal) =>
            (observing ??= (async () => {
                if (promoted.refused !== undefined) {
                    journal.unobserved = unobservedOf('failover', reader, journal.observations!, promoted)
                    return false
                }
                const deadline = AbortSignal.timeout(
                    Math.max(Date.parse(promoted.intentAt) + observeWithinMs - now(), 0)
                )
                const ok = await observe(
                    reader,
                    promoted.intentAt,
                    journal.observations!,
                    signal ? AbortSignal.any([signal, deadline]) : deadline
                )
                if (!ok) {
                    journal.unobserved = unobservedOf('failover', reader, journal.observations!, promoted)
                }
                return ok
            })()),

        release: () =>
            (released ??= (async () => {
                try {
                    if (writerOf(await describe()) === writer) {
                        return
                    }
                    const failback = await promote(writer)
                    journal.releaseIntentAt = failback.intentAt
                    journal.releaseObservations = []
                    const ok =
                        failback.refused === undefined &&
                        (await observe(
                            writer,
                            failback.intentAt,
                            journal.releaseObservations,
                            AbortSignal.timeout(observeWithinMs)
                        ))
                    if (!ok) {
                        journal.releaseError = unobservedOf('fail-back', writer, journal.releaseObservations, failback)
                    }
                } catch (error) {
                    journal.releaseError = `the fail-back could not start: ${messageOf(error)}`
                }
            })()),

        journal: () => ({
            ...journal,
            ...(journal.observations ? { observations: [...journal.observations] } : {}),
            ...(journal.releaseObservations ? { releaseObservations: [...journal.releaseObservations] } : {}),
        }),
    }

    async function requireIdleReader(): Promise<void> {
        const until = now() - (now() % MINUTE_MS)
        const query = {
            Id: 'acu',
            MetricStat: {
                Metric: {
                    Namespace: 'AWS/RDS',
                    MetricName: 'ServerlessDatabaseCapacity',
                    Dimensions: [{ Name: 'DBInstanceIdentifier', Value: reader }],
                },
                Period: 60,
                Stat: 'Maximum',
            },
        }
        const { MetricDataResults } = (await aws.call([
            'cloudwatch',
            'get-metric-data',
            '--metric-data-queries',
            JSON.stringify([query]),
            '--start-time',
            new Date(until - 2 * CAPACITY_MINUTES * MINUTE_MS).toISOString(),
            '--end-time',
            new Date(until).toISOString(),
        ])) as CapacityData
        const [{ Timestamps, Values }] = MetricDataResults
        const minutes = Timestamps.map((at, i) => ({ at: Date.parse(at), max: Values[i] }))
            .sort((a, b) => a.at - b.at)
            .slice(-CAPACITY_MINUTES)
        if (minutes.length < CAPACITY_MINUTES) {
            refuse(`${reader} has ${minutes.length} complete capacity minutes, under the ${CAPACITY_MINUTES} it needs`)
        }
        const newestEnd = minutes.at(-1)!.at + MINUTE_MS
        if (now() - newestEnd > CAPACITY_FRESH_WITHIN_MS) {
            refuse(`${reader}'s newest capacity minute ended ${Math.floor((now() - newestEnd) / 1000)}s ago`)
        }
        const busy = minutes.filter(({ max }) => max > IDLE_ACU)
        if (busy.length > 0) {
            refuse(
                `${reader} was above ${IDLE_ACU} ACU in its last ${CAPACITY_MINUTES} minutes: ${busy.map(({ at, max }) => `${max} at ${new Date(at).toISOString()}`).join(', ')}`
            )
        }
    }
}
