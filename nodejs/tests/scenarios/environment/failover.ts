import { setTimeout as sleep } from 'timers/promises'

import { Aws, AwsError } from '../cloud/aws'
import type { RunManifest } from '../cloud/lease'
import { RUN_TAG } from '../cloud/stack'
import type { WriterSample } from '../probe/writer-probe'
import { SCENARIO_SESSION_PREFIX } from './roles'
import { withPostgres } from './stack'

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
    manifest: RunManifest
    holdMs: number
    identity(): Promise<SqlIdentity>
    commits(): readonly WriterSample[]
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
// A 5xx code means the service may have started the promotion before it failed, so its outcome is unknown.
const SERVER_FAULT = /^(InternalFailure|InternalError|ServiceUnavailable|RequestTimeout)/

type Cluster = {
    Status: string
    TagList?: { Key: string; Value: string }[]
    DBClusterMembers?: { DBInstanceIdentifier: string; IsClusterWriter: boolean }[]
}

type CapacityData = { MetricDataResults: { Timestamps: string[]; Values: number[]; StatusCode?: string }[] }

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

export async function sqlIdentityOf(url: string): Promise<SqlIdentity> {
    const named = new URL(url)
    named.searchParams.set('application_name', `${SCENARIO_SESSION_PREFIX}failover`)
    const { rows } = await withPostgres(
        (client) =>
            client.query<{ instance: string; in_recovery: boolean }>(
                'SELECT aurora_db_instance_identifier() AS instance, pg_is_in_recovery() AS in_recovery'
            ),
        named.toString(),
        IDENTITY_TIMEOUT_MS
    )
    return { instance: rows[0].instance, inRecovery: rows[0].in_recovery }
}

export async function failOver({
    aws,
    manifest,
    holdMs,
    identity,
    commits,
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
    const leaseLeftMs = Date.parse(manifest.expiresAt) - Date.now()
    const neededMs = holdMs + 2 * observeWithinMs
    if (leaseLeftMs < neededMs) {
        refuse(
            `the lease has ${Math.floor(leaseLeftMs / 1000)}s left, under the ${neededMs / 1000}s the hold, settle and fail-back need`
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
        const intentAt = new Date().toISOString()
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
            return error instanceof AwsError && error.code !== undefined && !SERVER_FAULT.test(error.code)
                ? { intentAt, refused: messageOf(error) }
                : { intentAt, ambiguous: messageOf(error) }
        }
    }

    const observe = async (
        to: string,
        intentAt: string,
        into: Observation[],
        signal?: AbortSignal
    ): Promise<boolean> => {
        const since = Date.parse(intentAt)
        const deadline = since + observeWithinMs
        const seen = (name: ObservationName): boolean => into.some((observation) => observation.name === name)
        const record = (name: ObservationName, at: number): void => {
            if (!seen(name) && at <= deadline) {
                into.push({ name, at: new Date(at).toISOString() })
            }
        }
        const timeout = AbortSignal.timeout(Math.max(deadline - Date.now(), 0))
        const stop = signal ? AbortSignal.any([signal, timeout]) : timeout
        for (;;) {
            if (!seen('cluster_writer')) {
                const current = await describe().catch(() => undefined)
                if (current && writerOf(current) === to) {
                    record('cluster_writer', Date.now())
                }
            }
            if (!seen('sql_writer')) {
                const sql = await identity().catch(() => undefined)
                if (sql?.instance === to && !sql.inRecovery) {
                    record('sql_writer', Date.now())
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
            if (stop.aborted || Date.now() > deadline) {
                return false
            }
            await sleep(pollMs, undefined, { signal: stop }).catch(() => undefined)
        }
    }

    const settled = async (): Promise<Cluster> => {
        const deadline = Date.now() + observeWithinMs
        for (;;) {
            const current = await describe()
            if (current.Status === 'available' || Date.now() > deadline) {
                return current
            }
            await sleep(pollMs)
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
                const ok = await observe(reader, promoted.intentAt, journal.observations!, signal)
                if (!ok) {
                    journal.unobserved = unobservedOf('failover', reader, journal.observations!, promoted)
                }
                return ok
            })()),

        release: () =>
            (released ??= (async () => {
                try {
                    const current = await settled()
                    if (current.Status !== 'available') {
                        journal.releaseError = `${cluster} stayed ${current.Status} for ${observeWithinMs / 1000}s after the hold, so the fail-back did not start`
                        return
                    }
                    if (writerOf(current) === writer) {
                        return
                    }
                    const failback = await promote(writer)
                    journal.releaseIntentAt = failback.intentAt
                    journal.releaseObservations = []
                    const ok =
                        failback.refused === undefined &&
                        (await observe(writer, failback.intentAt, journal.releaseObservations))
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
        const startedAt = Date.now()
        const until = startedAt - (startedAt % MINUTE_MS)
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
        const [{ Timestamps, Values, StatusCode }] = MetricDataResults
        if (StatusCode !== undefined && StatusCode !== 'Complete') {
            refuse(`${reader}'s capacity read came back ${StatusCode}, not Complete`)
        }
        const sorted = Timestamps.map((at, i) => ({ at: Date.parse(at), max: Values[i] })).sort((a, b) => a.at - b.at)
        let consecutive = sorted.length > 0 ? 1 : 0
        while (
            consecutive < Math.min(sorted.length, CAPACITY_MINUTES) &&
            sorted.at(-consecutive)!.at - sorted.at(-consecutive - 1)!.at === MINUTE_MS
        ) {
            consecutive++
        }
        if (consecutive < CAPACITY_MINUTES) {
            refuse(
                `${reader} has ${consecutive} consecutive complete capacity minutes, under the ${CAPACITY_MINUTES} it needs`
            )
        }
        const minutes = sorted.slice(-CAPACITY_MINUTES)
        const newestEnd = minutes.at(-1)!.at + MINUTE_MS
        if (Date.now() - newestEnd > CAPACITY_FRESH_WITHIN_MS) {
            refuse(`${reader}'s newest capacity minute ended ${Math.floor((Date.now() - newestEnd) / 1000)}s ago`)
        }
        const busy = minutes.filter(({ max }) => max > IDLE_ACU)
        if (busy.length > 0) {
            refuse(
                `${reader} was above ${IDLE_ACU} ACU in its last ${CAPACITY_MINUTES} minutes: ${busy.map(({ at, max }) => `${max} at ${new Date(at).toISOString()}`).join(', ')}`
            )
        }
    }
}
