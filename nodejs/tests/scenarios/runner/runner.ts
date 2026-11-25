import { randomUUID } from 'crypto'
import { createReadStream, createWriteStream, existsSync, mkdirSync, statSync, writeFileSync } from 'fs'
import type { ProducerGlobalConfig } from 'node-rdkafka'
import os from 'os'
import path from 'path'
import { pipeline } from 'stream/promises'
import { setTimeout as sleep } from 'timers/promises'

import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PostgresRouter } from '~/common/utils/db/postgres'

import { residentBacklogOf } from '../backlog/backlog'
import { LOAD_PRODUCER_SETTING_PREFIX, LoadedCard, Named, Step, Target, stepsOf } from '../cards'
import { runManifestOf } from '../cloud/lease'
import { durationMs } from '../duration'
import { Environment, defaultStateDir } from '../environment/environment'
import { nameOf } from '../environment/identity'
import {
    ConsumerGroup,
    RoleSpec,
    SES_WEBHOOKS_GROUP,
    consumerGroupsOf,
    fetchRetriesOf,
    roleSpecs,
    secretsOf,
} from '../environment/roles'
import { cyclotronUrlOf, postgresUrlOf } from '../environment/stack'
import type { RoleExit } from '../environment/supervisor'
import { TOPOLOGY_FILE, Wiring, absentGroupsOf, hostsOf, missingTargets, nodesOf } from '../environment/topology'
import { DriveSummary, DrivenStep, SeedState, StepWindow, drive, seed } from '../generator/generator'
import { watchSesFeedback } from '../generator/ses-feedback'
import { OfferContext, kafkaEmit } from '../generator/traffic'
import { BarResult, WriterCpu, judgeBars } from '../judge/bars'
import { Convergence, InvariantResult, JournalEntry, JudgeOptions, createJudge } from '../judge/judge'
import {
    DriveWindow,
    Measurement,
    Probed,
    QueueSample,
    Sampled,
    Sampler,
    baselineOf,
    janitorResetsOf,
    measure,
    startSampler,
} from '../judge/measurements'
import { Ramp, rampOf, stepRatesOf, watchRamp } from '../judge/ramp'
import { edgeTruth } from '../judge/truth'
import { CyclotronProbe, Queue, createCyclotronProbe } from '../probe/cyclotron-probe'
import { Sampling, sampleEvery } from '../probe/every'
import { WriterProbe, WriterSample, createWriterProbe } from '../probe/writer-probe'
import { WEBHOOK_HOST } from '../provider-edge'
import { provenanceOf } from '../scorecard/provenance'
import { scorecardOf } from '../scorecard/scorecard'
import { publish } from '../scorecard/write'
import { reportToStore } from '../store/client'
import { ValveTimelineEntry, createValves } from '../valves/valves'
import { DependencyLoss, watchDependencies } from './dependency-watch'
import { writeJson } from './evidence-file'
import { openLiveLog } from './live'
import { SAVED_RUN_FILE, SavedRun } from './saved-run'
import { Admission, Status, admissionsOf, judgedInvariantsOf, statusOf, unobservedReasonOf } from './status'

const CLOUD_RUN_HOST_LABEL = 'run-host'
const EDGE_HOSTS = ['ses', WEBHOOK_HOST]

export type TargetRun = Pick<JudgeOptions, 'truth' | 'fetchRetries' | 'residentBacklog'> & {
    probe: Pick<CyclotronProbe, 'unfinishedJobs' | 'runningJobs'>
    groups: ConsumerGroup[]
    connect(): Promise<void>
    seed(signal: AbortSignal): Promise<SeedState>
    probes(teams: number[]): Promise<Probes>
    offers(): Promise<OfferContext>
    limit?(window: StepWindow): Promise<string | undefined>
    writeLogTails(evidenceDir: string): Promise<void>
    close(): Promise<void>
}

export type RunTarget = { name: Target; open(loaded: LoadedCard, runId: string): TargetRun }

export type RunVerdict = Omit<RunResult, 'recorded' | 'captured' | 'scorecardError' | 'stored' | 'storeError'>

export type RunResult = {
    runId: string
    status: Status
    statusReason: string
    recorded: boolean
    captured?: true
    scorecardError?: string
    stored?: true
    storeError?: string
    cardId: string
    cardHash: string
    profileHash: string
    topologyHash?: string
    origin: 'local-agent'
    target: Target
    units?: DriveSummary
    convergence?: Convergence
    janitorResets?: number
    invariants: InvariantResult[]
    measurements: Measurement[]
    admissions: Admission[]
    bars: BarResult[]
    ramp?: Ramp
    timeline: ValveTimelineEntry[]
    restarts?: RoleExit[]
    startedAt: string
    endedAt: string
    evidenceDir: string
}

export interface Runner {
    up(signal: AbortSignal): Promise<void>
    run(loaded: LoadedCard, signal: AbortSignal): Promise<RunResult>
    down(): Promise<void>
}

const HEALTH_INTERVAL_MS = 5000
const DELIVERY_TIMEOUT_MS = 10_000
const SEED_STATEMENT_TIMEOUT_MS = 5000
const SEED_WITHIN_MS = 60_000
const TOPOLOGY_WITHIN_MS = 30_000
const TOPOLOGY_EVERY_MS = 1000
const WRITER_PROBE_EVERY_MS = 1000
const QUEUE_PROBE_EVERY_MS = 5000
const PROBED_QUEUES: Queue[] = ['hogflow', 'email']

type Outcome = Pick<
    RunResult,
    | 'status'
    | 'statusReason'
    | 'units'
    | 'convergence'
    | 'janitorResets'
    | 'invariants'
    | 'measurements'
    | 'admissions'
    | 'restarts'
    | 'bars'
    | 'ramp'
>

export type Probes = { commits(): readonly WriterSample[]; queue(): readonly QueueSample[]; stop(): Promise<Probed> }

async function startProbes(
    cyclotronUrl: string,
    probe: CyclotronProbe,
    teams: number[],
    aurora: boolean
): Promise<Probes> {
    const writerProbe: WriterProbe = await createWriterProbe(cyclotronUrl, { aurora })
    const writer: Sampling<WriterSample> = sampleEvery(WRITER_PROBE_EVERY_MS, () => writerProbe.sample())
    const queue: Sampling<QueueSample> = sampleEvery(QUEUE_PROBE_EVERY_MS, async () => {
        const at = Date.now()
        return probe.counts({ teams, queues: PROBED_QUEUES }).then(
            (counts) => ({ at, ...counts }),
            (error: unknown) => ({ at, error: messageOf(error) })
        )
    })
    let stopping: Promise<Probed> | undefined
    return {
        commits: () => writer.taken(),
        queue: () => queue.taken(),
        stop: () =>
            (stopping ??= (async () => {
                const [writerSamples, queueSamples] = await Promise.all([writer.stop(), queue.stop()])
                await writerProbe.end()
                return { writer: writerSamples, queue: queueSamples }
            })()),
    }
}

function producerConfigOf(env: NodeJS.ProcessEnv): ProducerGlobalConfig {
    const settings = Object.entries(env).flatMap(([key, value]) =>
        key.startsWith(LOAD_PRODUCER_SETTING_PREFIX) && value
            ? [[key.slice(LOAD_PRODUCER_SETTING_PREFIX.length).replace(/_/g, '.').toLowerCase(), value]]
            : []
    )
    return { 'message.timeout.ms': DELIVERY_TIMEOUT_MS, ...Object.fromEntries(settings) }
}

function seedingUrlOf(spec: RoleSpec): string {
    const databaseUrl = postgresUrlOf(spec)
    if (!databaseUrl) {
        return databaseUrl
    }
    const url = new URL(databaseUrl)
    url.searchParams.set('statement_timeout', String(SEED_STATEMENT_TIMEOUT_MS))
    return url.toString()
}

function keepLogTails(stateDir: string, specs: RoleSpec[]): (evidenceDir: string) => Promise<void> {
    const sizeOf = (file: string): number => (existsSync(file) ? statSync(file).size : 0)
    const logs = specs.map((spec) => {
        const file = path.join(stateDir, `${nameOf(spec)}.log`)
        return { file, offset: sizeOf(file) }
    })
    return async (evidenceDir) => {
        mkdirSync(path.join(evidenceDir, 'logs'), { recursive: true })
        for (const { file, offset } of logs) {
            const tail = path.join(evidenceDir, 'logs', path.basename(file))
            const size = sizeOf(file)
            if (size > offset) {
                await pipeline(createReadStream(file, { start: offset, end: size - 1 }), createWriteStream(tail))
            } else {
                writeFileSync(tail, '')
            }
        }
    }
}

async function errorOf(write: () => Promise<void> | void): Promise<string | undefined> {
    try {
        await write()
        return undefined
    } catch (error) {
        return messageOf(error)
    }
}

function withEvidenceError(verdict: RunVerdict, error: string | undefined): RunVerdict {
    return error === undefined
        ? verdict
        : {
              ...verdict,
              status: 'invalid',
              statusReason: `${verdict.statusReason}; the evidence could not be written: ${error}`,
          }
}

type OpenPool = {
    ending: boolean
    end(): Promise<void>
    _clients: { connection: { stream: { destroy(): void } } }[]
}

function destroyConnections(postgres: PostgresRouter): void {
    const { pools } = postgres as unknown as { pools: Map<unknown, OpenPool> }
    for (const pool of new Set(pools.values())) {
        if (!pool.ending) {
            void pool.end().catch(() => undefined)
        }
        pool._clients.forEach((client) => client.connection.stream.destroy())
    }
}

class SeedingCutShort extends Error {}

function messageOf(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}

async function seedWithin(
    loaded: LoadedCard,
    seedingUrl: string,
    signal: AbortSignal,
    withinMs: number
): Promise<SeedState> {
    if (signal.aborted) {
        throw new Error('seeding was interrupted')
    }
    const deadline = AbortSignal.timeout(withinMs)
    const stop = AbortSignal.any([signal, deadline])
    const postgres = new PostgresRouter(
        { DATABASE_URL: seedingUrl, POSTGRES_CONNECTION_POOL_SIZE: 2 },
        'posthog-scenarios'
    )
    const stage = (async () => {
        try {
            return await seed(loaded, postgres, stop)
        } finally {
            await postgres.end()
        }
    })()
    let onStop = (): void => undefined
    const stopped = new Promise<never>((_, reject) => {
        onStop = () => reject(stop.reason)
        stop.addEventListener('abort', onStop, { once: true })
    })
    try {
        return await Promise.race([stage, stopped])
    } catch (error) {
        if (!stop.aborted) {
            throw error
        }
        stage.catch(() => undefined)
        destroyConnections(postgres)
        const why = deadline.aborted ? `seeding did not finish within ${withinMs} ms` : 'seeding was interrupted'
        throw new SeedingCutShort(`${why}; its connections were destroyed, restart required`)
    } finally {
        stop.removeEventListener('abort', onStop)
    }
}

const drivenStepsOf = (
    steps: readonly DrivenStep[],
    driveStartedAt: number,
    ramps: boolean
): (Step & { offeredUnits?: number })[] =>
    steps.map(({ scale, startedAt, endedAt, offeredUnits }) => ({
        scale,
        fromMs: startedAt - driveStartedAt,
        toMs: endedAt - driveStartedAt,
        ...(ramps && { offeredUnits }),
    }))

const firstStepOf = (drive: DriveWindow, [first]: Step[]): DriveWindow => ({
    ...drive,
    endedAt: Math.min(drive.endedAt, drive.startedAt + first.toMs),
})

const admittedWindowOf = (
    drive: LoadedCard['card']['drive'],
    window: DriveWindow,
    [first]: readonly DrivenStep[]
): DriveWindow =>
    drive.stopOnBreak && first
        ? { startedAt: first.startedAt, endedAt: first.endedAt }
        : firstStepOf(window, stepsOf(drive))

function cdpApiUrlsOf(environment: Environment): string[] {
    const urls = environment
        .roles()
        .filter(({ name }) => name === 'cdp-api')
        .map(({ url }) => url)
    if (urls.length === 0) {
        throw new Error('no cdp-api replica is running to take the intake offers')
    }
    return urls
}

function roundRobin(urls: readonly string[]): () => string {
    let next = 0
    return () => urls[next++ % urls.length]
}

function localTarget(
    environment: Environment,
    env: NodeJS.ProcessEnv,
    stateDir: string,
    seedWithinMs: number,
    aurora: boolean
): RunTarget {
    return {
        name: 'local',
        open(loaded) {
            const { profile } = loaded
            const edgeUrl = environment.edgeUrl()
            const secrets = secretsOf(env)
            const specs = roleSpecs(
                env,
                { url: edgeUrl },
                secrets,
                stateDir,
                profile.settings,
                undefined,
                profile.replicas
            )
            const writeLogTails = keepLogTails(stateDir, specs)
            const jwt = new ScopedServiceJwt(
                PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL,
                secrets.transactionalEmailJwtSecret
            )
            const groups = consumerGroupsOf(specs)
            const eventsTopic = groups[0].topics[0]
            const cyclotronUrl = cyclotronUrlOf(specs[0])
            const probe = createCyclotronProbe(cyclotronUrl)
            let producer: KafkaProducerWrapper | undefined
            return {
                truth: edgeTruth(edgeUrl),
                probe,
                residentBacklog: () => residentBacklogOf(profile, stateDir, cyclotronUrl),
                fetchRetries: fetchRetriesOf(specs.find(({ role }) => role === 'cdp-cyclotron-worker-hogflow')!),
                groups,
                async connect() {
                    producer = await KafkaProducerWrapper.createWithConfig(undefined, producerConfigOf(specs[0].env))
                },
                seed: (signal) => seedWithin(loaded, seedingUrlOf(specs[0]), signal, seedWithinMs),
                probes: (teams) => startProbes(cyclotronUrl, probe, teams, aurora),
                async offers() {
                    if (!producer) {
                        throw new Error('the load producer is not connected')
                    }
                    const cdpApi = { nextUrl: roundRobin(cdpApiUrlsOf(environment)), jwt }
                    const sesFeedback = await watchSesFeedback({
                        edgeUrl,
                        lag: () => environment.groupLag(SES_WEBHOOKS_GROUP),
                    })
                    return { emit: kafkaEmit(producer, eventsTopic), cdpApi, sesFeedback }
                },
                writeLogTails,
                async close() {
                    await producer?.disconnect()
                },
            }
        },
    }
}

export type RunnerOptions = {
    seedWithinMs?: number
    topologyWithinMs?: number
    topologyEveryMs?: number
    target?: RunTarget
}

export function createRunner(
    environment: Environment,
    env: NodeJS.ProcessEnv = process.env,
    {
        seedWithinMs = SEED_WITHIN_MS,
        topologyWithinMs = TOPOLOGY_WITHIN_MS,
        topologyEveryMs = TOPOLOGY_EVERY_MS,
        target,
    }: RunnerOptions = {}
): Runner {
    const stateDir = defaultStateDir(env)
    const manifest = runManifestOf(env)
    const runTarget = target ?? localTarget(environment, env, stateDir, seedWithinMs, manifest !== undefined)
    let restartRequired: Error | undefined
    let ranManifest = false

    const settledWiring = async (
        targets: string[],
        groups: ConsumerGroup[],
        signal: AbortSignal
    ): Promise<{ wiring: Wiring; nodes: string[]; missing: string[] }> => {
        const deadline = Date.now() + topologyWithinMs
        let previousHash: string | undefined
        let last: { wiring: Wiring; nodes: string[]; missing: string[] } | undefined
        for (;;) {
            const bound = AbortSignal.any([signal, AbortSignal.timeout(Math.max(deadline - Date.now(), 0))])
            const read = await environment.wiring(bound).then(
                (wiring) => ({ wiring }),
                (error: unknown) => ({ error })
            )
            if (signal.aborted) {
                throw new Error('the run was interrupted while it read its topology')
            }
            const late = Date.now() >= deadline
            if ('error' in read) {
                if (late && last) {
                    return last
                }
                if (late) {
                    throw read.error
                }
            } else {
                const nodes = nodesOf(read.wiring, EDGE_HOSTS)
                const missing = missingTargets(targets, nodes)
                const absent = absentGroupsOf(read.wiring, groups)
                const complete = missing.length === 0 && absent.length === 0
                const settled = complete && read.wiring.hash === previousHash
                last = { wiring: read.wiring, nodes, missing }
                if (settled || late) {
                    return last
                }
                previousHash = complete ? read.wiring.hash : undefined
            }
            await sleep(topologyEveryMs, undefined, { signal })
        }
    }

    const writerCpuFor = async (bars: Named[], window: DriveWindow, signal: AbortSignal): Promise<WriterCpu> => {
        if (!bars.some(({ name }) => name === 'writer_cpu_under')) {
            return []
        }
        if (manifest === undefined) {
            return { unsourced: 'the local stack has no Aurora writer to read CPU from' }
        }
        return environment.writerCpu(manifest, window, signal).catch((error: unknown) => ({
            unread: `the writer CPU read failed: ${messageOf(error)}`,
        }))
    }

    return {
        async up(signal) {
            await environment.up(signal)
        },

        async run(loaded, signal) {
            if (restartRequired !== undefined) {
                throw restartRequired
            }
            const { card, profile } = loaded
            if (manifest && ranManifest) {
                throw new Error(
                    `This runner already ran run ${manifest.runId} from its run manifest; a run host runs one card per manifest.`
                )
            }
            ranManifest = manifest !== undefined
            const runId = manifest?.runId ?? randomUUID()
            const startedAt = new Date().toISOString()
            const evidenceDir = path.join(stateDir, runId)
            const opened = runTarget.open(loaded, runId)
            const judge = createJudge(opened)
            const valves = createValves()
            using live = openLiveLog(evidenceDir)
            live.write({ type: 'start', at: Date.now(), runId, cardId: card.id, cardHash: loaded.cardHash })
            let outcome: Outcome = {
                status: 'invalid',
                statusReason: 'not started',
                invariants: [],
                measurements: [],
                admissions: [],
                bars: [],
            }
            let health: { stop(): Promise<DependencyLoss[]> } | undefined
            let dependencies: DependencyLoss[] = []
            let sampler: Sampler | undefined
            let sampled: Sampled = { samples: [], missed: [], host: [] }
            let probes: Probes | undefined
            let probed: Probed = { writer: [], queue: [] }
            const judging = new AbortController()
            let pendingJudgments = (): Promise<void> => Promise.resolve()
            let driven: DriveWindow | undefined
            let recorded: Wiring | undefined
            const writerCpuReads: (DriveWindow & { read: WriterCpu })[] = []
            const readWriterCpu = async (window: DriveWindow, readSignal: AbortSignal): Promise<WriterCpu> => {
                const read = await writerCpuFor(card.bars, window, readSignal)
                if (card.bars.some(({ name }) => name === 'writer_cpu_under')) {
                    writerCpuReads.push({ startedAt: window.startedAt, endedAt: window.endedAt, read })
                }
                return read
            }
            try {
                await opened.connect()
                live.write({ type: 'phase', at: Date.now(), phase: 'reset' })
                await environment.reset(profile.settings, profile.replicas).catch((error: unknown) => {
                    restartRequired = new Error(
                        `The reset before run ${runId} failed and stopped the environment: ${messageOf(error)}. Restart the runner, then run the card again.`
                    )
                    throw error
                })
                live.write({ type: 'phase', at: Date.now(), phase: 'seed' })
                const seeded = await opened.seed(signal).catch((error: unknown) => {
                    if (error instanceof SeedingCutShort) {
                        restartRequired = new Error(
                            `The seeding stage of run ${runId} was cut short and its connections were destroyed, so a write it sent may still land in the next card. Restart the runner, then run the card again.`
                        )
                    }
                    throw error
                })
                await judge.open(seeded)
                const exitsBefore = environment.exits().length
                const { wiring, nodes, missing } = await settledWiring(
                    card.valves.map(({ target }) => target),
                    opened.groups,
                    signal
                )
                recorded = wiring
                if (missing.length > 0) {
                    throw new Error(
                        `the card targets ${missing.join(', ')}, which this run's topology does not have; it found ${nodes.join(', ')}`
                    )
                }
                health = watchDependencies(
                    () => environment.dependencyHealth().then(({ down }) => down),
                    HEALTH_INTERVAL_MS
                )
                sampler = await startSampler(
                    environment.roles().map(({ name, replica, metricsUrl }) => ({ role: name, replica, metricsUrl }))
                )
                probes = await opened.probes(seeded.teamIds)
                const driveStartedAt = Date.now()
                live.write({
                    type: 'phase',
                    at: driveStartedAt,
                    phase: 'drive',
                    driveForMs: durationMs(card.drive.for),
                })
                const sampling = { sampler, probes }
                void live.follow({
                    timeline: () => valves.timeline(),
                    samples: () => sampling.sampler.taken(),
                    queue: () => sampling.probes.queue(),
                    writer: () => sampling.probes.commits(),
                    journal: () => judge.evidence().journal,
                    truth: opened.truth,
                })
                await valves.start(card.valves, {
                    environment,
                    probe: opened.probe,
                    teams: seeded.teamIds,
                    commits: probes.commits,
                    manifest,
                })
                const offers = await opened.offers()
                const windowOpen = new AbortController()
                void sleep(durationMs(card.drive.for), undefined, { signal: windowOpen.signal })
                    .then(() => valves.releaseAll())
                    .catch(() => undefined)
                const liveSignal = AbortSignal.any([signal, judging.signal])
                const watch = card.drive.stopOnBreak
                    ? watchRamp(
                          {
                              minOffered: card.drive.minOffered,
                              bars: card.bars,
                              gates: card.gates,
                              judgesRefusals: card.invariants.some(({ name }) => name === 'refused_at_intake'),
                              driveStartedAt,
                              hostCpuCeiling: profile.host?.cpuCeiling,
                              journal: () => judge.evidence().journal,
                              samples: () => sampling.sampler.taken(),
                              host: () => sampling.sampler.host(),
                              queue: () => sampling.probes.queue(),
                              profile,
                              writerCpu: (window) => readWriterCpu(window, liveSignal),
                              targetLimit: opened.limit,
                          },
                          liveSignal
                      )
                    : undefined
                pendingJudgments = () => watch?.pending() ?? Promise.resolve()
                const recorder = watch
                    ? {
                          record: (unit: JournalEntry) => {
                              judge.record(unit)
                              watch.record(unit)
                          },
                      }
                    : judge
                const units = await drive(loaded, seeded, recorder, AbortSignal.any([signal, valves.refusal]), {
                    ...offers,
                    runId,
                    halt: watch?.halt,
                    gate: watch?.gate,
                }).finally(() => windowOpen.abort())
                const steps = drivenStepsOf(units.steps, driveStartedAt, card.drive.stopOnBreak === true)
                const driveWindow: DriveWindow = {
                    startedAt: driveStartedAt,
                    endedAt: Math.min(Date.now(), units.steps.at(-1)?.endedAt ?? Infinity),
                }
                driven = driveWindow
                await valves.releaseAll()
                live.write({ type: 'phase', at: Date.now(), phase: 'converge' })
                const converged = await judge.converge(durationMs(card.convergeWithin), signal)
                await pendingJudgments()
                const stop = watch?.stopped()
                live.write({ type: 'phase', at: Date.now(), phase: 'judge' })
                probed = await probes.stop()
                sampled = await sampler.stop()
                await live.stop()
                dependencies = await health.stop()
                const janitorResets = janitorResetsOf({ ...sampled, sampledFrom: sampler.sampledFrom })
                const checked = await judge.check(card.invariants, card.gates, { janitorResets }, signal)
                const { unread } = judge.evidence()
                const convergence: Convergence = unread === undefined ? converged : { ...converged, unread }
                const invariants = judgedInvariantsOf(checked, convergence)
                const evidence = {
                    ...judge.evidence(),
                    ...sampled,
                    ...probed,
                    sampledFrom: sampler.sampledFrom,
                    drive: driveWindow,
                    steps,
                    timeline: valves.timeline(),
                }
                const measurements = measure(card.measure, evidence)
                const admissions = admissionsOf(
                    profile,
                    baselineOf({ ...evidence, drive: admittedWindowOf(card.drive, driveWindow, units.steps) }),
                    units.steps[0]?.scale
                )
                const bars = judgeBars(card.bars, {
                    ...evidence,
                    hostCpuCeiling: profile.host?.cpuCeiling,
                    writerCpu: await readWriterCpu(driveWindow, signal),
                    settled: watch?.settled(),
                })
                const ramp = card.drive.stopOnBreak
                    ? rampOf({
                          planned: stepsOf(card.drive),
                          steps: units.steps,
                          minOffered: card.drive.minOffered,
                          stop,
                          bars,
                          invariants,
                          gates: card.gates,
                          journal: evidence.journal,
                          admissions,
                          convergence,
                          rates: stepRatesOf(
                              units.steps,
                              evidence,
                              {
                                  lost: card.invariants.some(({ name }) => name === 'at_least_once'),
                                  duplicates: card.invariants.some(({ name }) => name === 'duplicate_sends'),
                              },
                              convergence
                          ),
                      })
                    : undefined
                const verdict = statusOf({
                    admissions,
                    minOffered: card.drive.minOffered,
                    units,
                    down: dependencies,
                    convergence,
                    invariants,
                    timeline: valves.timeline(),
                    exits: environment.exits().slice(exitsBefore),
                    writer: probed.writer,
                    drive: driveWindow,
                    bars,
                    ramp,
                })
                outcome = {
                    ...verdict,
                    units,
                    convergence,
                    janitorResets,
                    invariants,
                    measurements,
                    admissions,
                    bars,
                    ...(ramp && { ramp }),
                }
                if (signal.aborted) {
                    outcome = { ...outcome, status: 'invalid', statusReason: 'the run was interrupted' }
                } else if (valves.refusal.aborted) {
                    outcome = {
                        ...outcome,
                        status: 'invalid',
                        statusReason: unobservedReasonOf(valves.refusal.reason as ValveTimelineEntry),
                    }
                }
            } catch (error) {
                outcome = {
                    ...outcome,
                    status: 'invalid',
                    statusReason: `the run stopped: ${messageOf(error)}`,
                }
            } finally {
                judging.abort()
                await pendingJudgments()
                await valves.releaseAll()
                dependencies = (await health?.stop()) ?? dependencies
                probed = (await probes?.stop()) ?? probed
                sampled = (await sampler?.stop()) ?? sampled
                await live.stop()
                try {
                    await opened.close()
                } catch (error) {
                    restartRequired = new Error(
                        `The load producer of run ${runId} did not disconnect and may still send its buffered messages into this card. Restart the runner, then run the card again.`
                    )
                    const failed = `the load producer did not disconnect: ${messageOf(error)}`
                    outcome = {
                        ...outcome,
                        status: 'invalid',
                        statusReason: outcome.status === 'passed' ? failed : `${outcome.statusReason}; ${failed}`,
                    }
                }
            }
            const verdict: RunVerdict = {
                runId,
                ...outcome,
                cardId: card.id,
                cardHash: loaded.cardHash,
                profileHash: loaded.profileHash,
                ...(recorded && recorded.processes.length > 0 ? { topologyHash: recorded.hash } : {}),
                origin: 'local-agent',
                target: runTarget.name,
                timeline: valves.timeline(),
                startedAt,
                endedAt: new Date().toISOString(),
                evidenceDir,
            }
            const provenance = provenanceOf()
            const host = manifest ? CLOUD_RUN_HOST_LABEL : os.hostname()
            const evidenceError = await errorOf(async () => {
                await opened.writeLogTails(evidenceDir)
                const { journal, truth } = judge.evidence()
                writeJson(evidenceDir, 'journal.json', journal)
                writeJson(evidenceDir, 'truth.json', truth)
                writeJson(evidenceDir, 'metrics.json', sampled)
                writeJson(evidenceDir, 'probes.json', { drive: driven ?? null, ...probed, dependencies })
                if (writerCpuReads.length > 0) {
                    writeJson(evidenceDir, 'writer-cpu.json', writerCpuReads)
                }
                if (recorded) {
                    writeJson(evidenceDir, TOPOLOGY_FILE, { ...recorded, hosts: hostsOf(truth) })
                }
                writeJson(evidenceDir, SAVED_RUN_FILE, {
                    ...verdict,
                    host,
                    event: scorecardOf(verdict, loaded, provenance),
                } satisfies SavedRun)
            })
            const judged = withEvidenceError(verdict, evidenceError)
            live.write({ type: 'end', at: Date.now(), status: judged.status, statusReason: judged.statusReason })
            const scorecard = scorecardOf(judged, loaded, provenance)
            const written = await publish(scorecard, env, signal)
            const reported = await reportToStore({ scorecard, host }, env)
            return {
                ...judged,
                recorded: written.recorded,
                captured: written.captured,
                scorecardError: written.problem,
                stored: reported.stored || undefined,
                storeError: reported.problem,
            }
        },

        async down() {
            await environment.down()
        },
    }
}
