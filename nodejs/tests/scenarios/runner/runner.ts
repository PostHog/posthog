import { randomUUID } from 'crypto'
import {
    createReadStream,
    createWriteStream,
    existsSync,
    mkdirSync,
    renameSync,
    rmSync,
    statSync,
    writeFileSync,
} from 'fs'
import type { ProducerGlobalConfig } from 'node-rdkafka'
import path from 'path'
import { pipeline } from 'stream/promises'
import { setTimeout as sleep } from 'timers/promises'

import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PostgresRouter } from '~/common/utils/db/postgres'

import { residentBacklogOf } from '../backlog/backlog'
import { LOAD_PRODUCER_SETTING_PREFIX, LoadedCard } from '../cards'
import { durationMs } from '../duration'
import { Environment, defaultStateDir } from '../environment/environment'
import { nameOf } from '../environment/identity'
import {
    RoleSpec,
    SES_WEBHOOKS_GROUP,
    consumerGroupsOf,
    fetchRetriesOf,
    roleSpecs,
    secretsOf,
} from '../environment/roles'
import { cyclotronUrlOf, postgresUrlOf } from '../environment/stack'
import { DriveSummary, SeedState, drive, seed } from '../generator/generator'
import { watchSesFeedback } from '../generator/ses-feedback'
import { Convergence, InvariantResult, createJudge } from '../judge/judge'
import {
    DriveWindow,
    Measurement,
    Probed,
    QueueSample,
    Sampled,
    Sampler,
    baselineOf,
    measure,
    startSampler,
} from '../judge/measurements'
import { CyclotronProbe, Queue, createCyclotronProbe } from '../probe/cyclotron-probe'
import { Sampling, sampleEvery } from '../probe/every'
import { WriterProbe, WriterSample, createWriterProbe } from '../probe/writer-probe'
import { provenanceOf } from '../scorecard/provenance'
import { scorecardOf } from '../scorecard/scorecard'
import { publish } from '../scorecard/write'
import { ValveTimelineEntry, createValves } from '../valves/valves'
import { Admission, Status, admissionsOf, statusOf } from './status'

export type RunVerdict = Omit<RunResult, 'recorded' | 'captured' | 'scorecardError'>

export type RunResult = {
    runId: string
    status: Status
    statusReason: string
    recorded: boolean
    captured?: true
    scorecardError?: string
    cardId: string
    cardHash: string
    profileHash: string
    origin: 'local-agent'
    units?: DriveSummary
    convergence?: Convergence
    invariants: InvariantResult[]
    measurements: Measurement[]
    admissions: Admission[]
    timeline: ValveTimelineEntry[]
    startedAt: string
    endedAt: string
    evidenceDir: string
}

export interface Runner {
    up(): Promise<void>
    run(loaded: LoadedCard, signal: AbortSignal): Promise<RunResult>
    down(): Promise<void>
}

const HEALTH_INTERVAL_MS = 5000
const DELIVERY_TIMEOUT_MS = 10_000
const SEED_STATEMENT_TIMEOUT_MS = 5000
const WRITER_PROBE_EVERY_MS = 1000
const QUEUE_PROBE_EVERY_MS = 5000
const PROBED_QUEUES: Queue[] = ['hogflow', 'email']

type Outcome = Pick<
    RunResult,
    'status' | 'statusReason' | 'units' | 'convergence' | 'invariants' | 'measurements' | 'admissions'
>

type Probes = { stop(): Promise<Probed> }

async function startProbes(cyclotronUrl: string, probe: CyclotronProbe, teams: number[]): Promise<Probes> {
    const writerProbe: WriterProbe = await createWriterProbe(cyclotronUrl)
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

function watchHealth(environment: Environment): () => Promise<string[]> {
    const down = new Set<string>()
    const stopped = new AbortController()
    const watching = (async () => {
        while (!stopped.signal.aborted) {
            const health = await environment.dependencyHealth().catch(() => ({ down: ['health check'] }))
            health.down.forEach((name) => down.add(name))
            await sleep(HEALTH_INTERVAL_MS, undefined, { signal: stopped.signal }).catch(() => undefined)
        }
    })()
    return async () => {
        stopped.abort()
        await watching
        return [...down]
    }
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

function writeJson(evidenceDir: string, name: string, value: unknown): void {
    const file = path.join(evidenceDir, name)
    const partial = `${file}.partial`
    try {
        writeFileSync(partial, JSON.stringify(value, null, 2))
        renameSync(partial, file)
    } catch (error) {
        rmSync(partial, { force: true })
        throw error
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

function messageOf(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}

async function seedRun(loaded: LoadedCard, seedingUrl: string, signal: AbortSignal): Promise<SeedState> {
    if (signal.aborted) {
        throw new Error('seeding was interrupted')
    }
    const postgres = new PostgresRouter(
        { DATABASE_URL: seedingUrl, POSTGRES_CONNECTION_POOL_SIZE: 2 },
        'posthog-scenarios'
    )
    try {
        return await seed(loaded, postgres, signal)
    } finally {
        await postgres.end()
    }
}

export function createRunner(environment: Environment, env: NodeJS.ProcessEnv = process.env): Runner {
    const stateDir = defaultStateDir(env)
    let restartRequired: Error | undefined

    return {
        async up() {
            await environment.up()
        },

        async run(loaded, signal) {
            if (restartRequired !== undefined) {
                throw restartRequired
            }
            const { card, profile } = loaded
            const runId = randomUUID()
            const startedAt = new Date().toISOString()
            const evidenceDir = path.join(stateDir, runId)
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
            const cdpApi = {
                url: environment.role('cdp-api').url,
                jwt: new ScopedServiceJwt(
                    PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL,
                    secrets.transactionalEmailJwtSecret
                ),
            }
            const [
                {
                    topics: [eventsTopic],
                },
            ] = consumerGroupsOf(specs)
            const probe = createCyclotronProbe(cyclotronUrlOf(specs[0]))
            const judge = createJudge({
                edgeUrl,
                probe,
                residentBacklog: () => residentBacklogOf(profile, stateDir, cyclotronUrlOf(specs[0])),
                fetchRetries: fetchRetriesOf(specs.find(({ role }) => role === 'cdp-cyclotron-worker-hogflow')!),
            })
            const valves = createValves()
            let outcome: Outcome = {
                status: 'invalid',
                statusReason: 'not started',
                invariants: [],
                measurements: [],
                admissions: [],
            }
            let stopHealth: (() => Promise<string[]>) | undefined
            let sampler: Sampler | undefined
            let sampled: Sampled = { samples: [], missed: [], host: [] }
            let probes: Probes | undefined
            let probed: Probed = { writer: [], queue: [] }
            let driven: DriveWindow | undefined
            let producer: KafkaProducerWrapper | undefined
            try {
                producer = await KafkaProducerWrapper.createWithConfig(undefined, producerConfigOf(specs[0].env))
                await environment.reset(profile.settings, profile.replicas).catch((error: unknown) => {
                    restartRequired = new Error(
                        `The reset before run ${runId} failed and stopped the environment: ${messageOf(error)}. Restart the runner, then run the card again.`
                    )
                    throw error
                })
                const seeded = await seedRun(loaded, seedingUrlOf(specs[0]), signal)
                await judge.open(seeded)
                const exitsBefore = environment.exits().length
                stopHealth = watchHealth(environment)
                sampler = await startSampler(
                    environment.roles().map(({ name, replica, metricsUrl }) => ({ role: name, replica, metricsUrl }))
                )
                probes = await startProbes(cyclotronUrlOf(specs[0]), probe, seeded.teamIds)
                const driveStartedAt = Date.now()
                await valves.start(card.valves, { environment, probe, teams: seeded.teamIds })
                const sesFeedback = await watchSesFeedback({
                    edgeUrl,
                    lag: () => environment.groupLag(SES_WEBHOOKS_GROUP),
                })
                const windowOpen = new AbortController()
                void sleep(durationMs(card.drive.for), undefined, { signal: windowOpen.signal })
                    .then(() => valves.releaseAll())
                    .catch(() => undefined)
                const units = await drive(loaded, seeded, judge, signal, {
                    producer,
                    eventsTopic,
                    cdpApi,
                    sesFeedback,
                    runId,
                }).finally(() => windowOpen.abort())
                const driveWindow: DriveWindow = { startedAt: driveStartedAt, endedAt: Date.now() }
                driven = driveWindow
                await valves.releaseAll()
                const convergence = await judge.converge(durationMs(card.convergeWithin), signal)
                probed = await probes.stop()
                sampled = await sampler.stop()
                const down = await stopHealth()
                const invariants = await judge.check(card.invariants, card.gates)
                const evidence = {
                    ...judge.evidence(),
                    ...sampled,
                    ...probed,
                    sampledFrom: sampler.sampledFrom,
                    drive: driveWindow,
                    timeline: valves.timeline(),
                }
                const measurements = measure(card.measure, evidence)
                const admissions = admissionsOf(profile, baselineOf(evidence))
                const verdict = statusOf({
                    admissions,
                    minOffered: card.drive.minOffered,
                    units,
                    down,
                    convergence,
                    invariants,
                    timeline: valves.timeline(),
                    exits: environment.exits().slice(exitsBefore),
                })
                outcome = { ...verdict, units, convergence, invariants, measurements, admissions }
                if (signal.aborted) {
                    outcome = { ...outcome, status: 'invalid', statusReason: 'the run was interrupted' }
                }
            } catch (error) {
                outcome = {
                    ...outcome,
                    status: 'invalid',
                    statusReason: `the run stopped: ${messageOf(error)}`,
                }
            } finally {
                await valves.releaseAll()
                await stopHealth?.()
                probed = (await probes?.stop()) ?? probed
                sampled = (await sampler?.stop()) ?? sampled
                await producer?.disconnect()
            }
            const verdict: RunVerdict = {
                runId,
                ...outcome,
                cardId: card.id,
                cardHash: loaded.cardHash,
                profileHash: loaded.profileHash,
                origin: 'local-agent',
                timeline: valves.timeline(),
                startedAt,
                endedAt: new Date().toISOString(),
                evidenceDir,
            }
            const provenance = provenanceOf()
            const evidenceError = await errorOf(async () => {
                await writeLogTails(evidenceDir)
                const { journal, truth } = judge.evidence()
                writeJson(evidenceDir, 'journal.json', journal)
                writeJson(evidenceDir, 'truth.json', truth)
                writeJson(evidenceDir, 'metrics.json', sampled)
                writeJson(evidenceDir, 'probes.json', { drive: driven ?? null, ...probed })
                writeJson(evidenceDir, 'scorecard.json', {
                    ...verdict,
                    event: scorecardOf(verdict, loaded, provenance),
                })
            })
            const judged = withEvidenceError(verdict, evidenceError)
            const written = await publish(scorecardOf(judged, loaded, provenance), env, signal)
            return {
                ...judged,
                recorded: written.recorded,
                captured: written.captured,
                scorecardError: written.problem,
            }
        },

        async down() {
            await environment.down()
        },
    }
}
