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
    signal?: AbortSignal
}

const POLL_MS = 1000
const OBSERVE_WITHIN_MS = 5 * 60_000
export const FAILOVER_RELEASE_WITHIN_MS = 2 * OBSERVE_WITHIN_MS
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

type Outcome<T> = { value: T } | { error: unknown } | { stopped: true }

// The aws CLI and the identity query can stall past any deadline, so a stop abandons the answer instead of awaiting it.
const outcomeBefore = <T>(work: Promise<T>, stop: AbortSignal): Promise<Outcome<T>> =>
    new Promise((resolve) => {
        const abandon = (): void => resolve({ stopped: true })
        work.then(
            (value) => resolve({ value }),
            (error: unknown) => resolve({ error })
        ).finally(() => stop.removeEventListener('abort', abandon))
        if (stop.aborted) {
            return abandon()
        }
        stop.addEventListener('abort', abandon, { once: true })
    })

const answerBefore = async <T>(work: Promise<T>, stop: AbortSignal): Promise<T | undefined> => {
    const outcome = await outcomeBefore(work, stop)
    return 'value' in outcome ? outcome.value : undefined
}

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

type Promoted = { intentAt: string; ambiguous?: string; refused?: string }

export async function failOver({
    aws,
    manifest,
    holdMs,
    identity,
    commits,
    pollMs = POLL_MS,
    observeWithinMs = OBSERVE_WITHIN_MS,
    signal,
}: FailoverOptions): Promise<FailoverActuation> {
    const cluster = manifest.stackName
    const writer = `${cluster}-writer`
    const reader = `${cluster}-reader`
    const journal: FailoverJournal = {}
    const refuse = (reason: string): never => {
        throw new Error(`pg.failover refused: ${reason}`)
    }
    const applying = AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(observeWithinMs)])
    const required = async <T>(work: Promise<T>): Promise<T> => {
        const outcome = await outcomeBefore(work, applying)
        if ('stopped' in outcome) {
            refuse(`AWS had not answered when the apply stopped, on release or after ${observeWithinMs / 1000}s`)
        }
        if ('error' in outcome) {
            throw outcome.error
        }
        return (outcome as { value: T }).value
    }

    const describe = async (): Promise<Cluster> =>
        (
            (await aws.call(['rds', 'describe-db-clusters', '--db-cluster-identifier', cluster])) as {
                DBClusters: Cluster[]
            }
        ).DBClusters[0]
    const writerOf = (described: Cluster): string | undefined =>
        described.DBClusterMembers?.find(({ IsClusterWriter }) => IsClusterWriter)?.DBInstanceIdentifier

    const { Account } = (await required(aws.call(['sts', 'get-caller-identity']))) as { Account: string }
    if (Account !== manifest.account) {
        refuse(`the caller is in account ${Account}, not the run's account ${manifest.account}`)
    }
    const described = await required(describe())
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

    const promote = async (to: string, stop: AbortSignal, intentAt: string): Promise<Promoted> => {
        const outcome = await outcomeBefore(
            aws.call([
                'rds',
                'failover-db-cluster',
                '--db-cluster-identifier',
                cluster,
                '--target-db-instance-identifier',
                to,
            ]),
            stop
        )
        if ('value' in outcome) {
            return { intentAt }
        }
        if ('stopped' in outcome) {
            return { intentAt, ambiguous: `AWS had not answered within ${observeWithinMs / 1000}s or before release` }
        }
        const { error } = outcome
        return error instanceof AwsError && error.code !== undefined && !SERVER_FAULT.test(error.code)
            ? { intentAt, refused: messageOf(error) }
            : { intentAt, ambiguous: messageOf(error) }
    }

    const observe = async (
        to: string,
        intentAt: string,
        into: Observation[],
        signal?: AbortSignal
    ): Promise<boolean> => {
        const since = Date.parse(intentAt)
        const deadline = since + observeWithinMs
        const timeout = AbortSignal.timeout(Math.max(deadline - Date.now(), 0))
        const stop = signal ? AbortSignal.any([signal, timeout]) : timeout
        const seen = (name: ObservationName): boolean => into.some((observation) => observation.name === name)
        const record = (name: ObservationName, at: number): void => {
            if (!seen(name) && at <= deadline && !stop.aborted) {
                into.push({ name, at: new Date(at).toISOString() })
                into.sort((a, b) => OBSERVATIONS.indexOf(a.name) - OBSERVATIONS.indexOf(b.name))
            }
        }
        // Each stage polls on its own, so a stalled cluster read never delays or censors the SQL and commit stages.
        const poll = async (name: ObservationName, seenAt: () => Promise<number | undefined>): Promise<void> => {
            while (!seen(name)) {
                const at = await seenAt()
                if (at !== undefined) {
                    record(name, at)
                }
                if (seen(name) || stop.aborted || Date.now() > deadline) {
                    return
                }
                await sleep(pollMs, undefined, { signal: stop }).catch(() => undefined)
            }
        }
        await Promise.all([
            poll('cluster_writer', async () => {
                const current = await answerBefore(describe(), stop)
                return current && writerOf(current) === to ? Date.now() : undefined
            }),
            poll('sql_writer', async () => {
                const sql = await answerBefore(identity(), stop)
                return sql?.instance === to && !sql.inRecovery ? Date.now() : undefined
            }),
            poll('first_probe_commit', () => {
                const commit = commits().find(
                    (sample) => sample.ok && sample.instance === to && sample.at + sample.latencyMs > since
                )
                return Promise.resolve(commit && commit.at + commit.latencyMs)
            }),
        ])
        return OBSERVATIONS.every(seen)
    }

    const settled = async (movingFrom: string | undefined): Promise<Cluster | undefined> => {
        const stop = AbortSignal.timeout(observeWithinMs)
        let last: Cluster | undefined
        while (!stop.aborted) {
            const current = await answerBefore(describe(), stop)
            if (stop.aborted) {
                break
            }
            last = current ?? last
            if (current?.Status === 'available' && writerOf(current) !== movingFrom) {
                return current
            }
            await sleep(pollMs, undefined, { signal: stop }).catch(() => undefined)
        }
        return last
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

    // Observation runs from the intent, so a promotion AWS accepted counts even while the answer to its request stalls.
    // The answer is awaited only to explain a promotion that was not observed.
    const unobservedFrom = async (
        what: string,
        to: string,
        intentAt: string,
        promoting: Promise<Promoted>,
        into: Observation[],
        signal?: AbortSignal
    ): Promise<string | undefined> => {
        const refusal = new AbortController()
        let answer: Promoted | undefined
        void promoting.then((promoted) => {
            answer = promoted
            if (promoted.refused !== undefined) {
                refusal.abort()
            }
        })
        const stop = signal ? AbortSignal.any([signal, refusal.signal]) : refusal.signal
        if (await observe(to, intentAt, into, stop)) {
            return undefined
        }
        // The hold ends observation even while the answer to the request is still pending.
        const promoted = answer ??
            (signal ? await answerBefore(promoting, signal) : await promoting) ?? {
                intentAt,
                ambiguous: 'AWS had not answered when the hold ended',
            }
        return unobservedOf(what, to, into, promoted)
    }

    if (applying.aborted) {
        refuse('the apply stopped before the failover request was sent')
    }
    // Checked last, because the precondition reads can take until the apply deadline.
    const leaseLeftMs = Date.parse(manifest.expiresAt) - Date.now()
    const neededMs = holdMs + 2 * observeWithinMs
    if (leaseLeftMs < neededMs) {
        refuse(
            `the lease has ${Math.floor(leaseLeftMs / 1000)}s left, under the ${neededMs / 1000}s the hold, settle and fail-back need`
        )
    }
    const intentAt = new Date().toISOString()
    const promoting = promote(reader, applying, intentAt)
    let answered: Promoted | undefined
    void promoting.then((promoted) => {
        answered = promoted
    })
    journal.intentAt = intentAt
    journal.observations = []
    let observing: Promise<boolean> | undefined
    let released: Promise<void> | undefined

    return {
        observed: (signal) =>
            (observing ??= (async () => {
                journal.unobserved = await unobservedFrom(
                    'failover',
                    reader,
                    intentAt,
                    promoting,
                    journal.observations!,
                    signal
                )
                return journal.unobserved === undefined
            })()),

        release: () =>
            (released ??= (async () => {
                try {
                    // Release never waits for the answer: an unanswered request may still land, which settling covers.
                    // The control plane can show the old writer for a while after it accepted the promotion.
                    const mayStillLand =
                        answered?.refused === undefined &&
                        !journal.observations!.some(({ name }) => name === 'cluster_writer')
                    const current = await settled(mayStillLand ? writer : undefined)
                    if (current?.Status !== 'available') {
                        journal.releaseError = `${cluster} stayed ${current?.Status ?? 'unanswered'} for ${observeWithinMs / 1000}s after the hold, so the fail-back did not start`
                        return
                    }
                    if (writerOf(current) === writer) {
                        if (mayStillLand) {
                            journal.releaseError = `${reader} had not taken over ${observeWithinMs / 1000}s after the hold, so the failover request may still land`
                        }
                        return
                    }
                    const failbackAt = new Date().toISOString()
                    journal.releaseIntentAt = failbackAt
                    journal.releaseObservations = []
                    journal.releaseError = await unobservedFrom(
                        'fail-back',
                        writer,
                        failbackAt,
                        promote(writer, AbortSignal.timeout(observeWithinMs), failbackAt),
                        journal.releaseObservations
                    )
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
        const { MetricDataResults } = (await required(
            aws.call([
                'cloudwatch',
                'get-metric-data',
                '--metric-data-queries',
                JSON.stringify([query]),
                '--start-time',
                new Date(until - 2 * CAPACITY_MINUTES * MINUTE_MS).toISOString(),
                '--end-time',
                new Date(until).toISOString(),
            ])
        )) as CapacityData
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
