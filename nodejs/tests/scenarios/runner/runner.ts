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

import { CdpRole, LOAD_PRODUCER_SETTING_PREFIX, LoadedCard } from '../cards'
import { durationMs } from '../duration'
import { Environment, defaultStateDir } from '../environment/environment'
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
import { Measurement, Sampled, Sampler, measure, startSampler } from '../judge/measurements'
import { createCyclotronProbe } from '../probe/cyclotron-probe'
import { provenanceOf } from '../scorecard/provenance'
import { scorecardOf } from '../scorecard/scorecard'
import { publish } from '../scorecard/write'
import { ValveTimelineEntry, createValves } from '../valves/valves'
import { Status, statusOf } from './status'

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
const SEED_WITHIN_MS = 60_000

type Outcome = Pick<RunResult, 'status' | 'statusReason' | 'units' | 'convergence' | 'invariants' | 'measurements'>

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

function keepLogTails(stateDir: string): (evidenceDir: string) => Promise<void> {
    const sizeOf = (file: string): number => (existsSync(file) ? statSync(file).size : 0)
    const logs = CdpRole.options.map((role) => {
        const file = path.join(stateDir, `${role}.log`)
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

export type RunnerOptions = { seedWithinMs?: number }

export function createRunner(
    environment: Environment,
    env: NodeJS.ProcessEnv = process.env,
    { seedWithinMs = SEED_WITHIN_MS }: RunnerOptions = {}
): Runner {
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
            const writeLogTails = keepLogTails(stateDir)
            const edgeUrl = environment.edgeUrl()
            const secrets = secretsOf(env)
            const specs = roleSpecs(env, { url: edgeUrl }, secrets, stateDir, profile.settings)
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
                fetchRetries: fetchRetriesOf(specs.find(({ role }) => role === 'cdp-cyclotron-worker-hogflow')!),
            })
            const valves = createValves()
            let outcome: Outcome = { status: 'invalid', statusReason: 'not started', invariants: [], measurements: [] }
            let stopHealth: (() => Promise<string[]>) | undefined
            let sampler: Sampler | undefined
            let sampled: Sampled = { samples: [], missed: [] }
            let producer: KafkaProducerWrapper | undefined
            try {
                producer = await KafkaProducerWrapper.createWithConfig(undefined, producerConfigOf(specs[0].env))
                await environment.reset(profile.settings).catch((error: unknown) => {
                    restartRequired = new Error(
                        `The reset before run ${runId} failed and stopped the environment: ${messageOf(error)}. Restart the runner, then run the card again.`
                    )
                    throw error
                })
                const seeded = await seedWithin(loaded, seedingUrlOf(specs[0]), signal, seedWithinMs).catch(
                    (error: unknown) => {
                        if (error instanceof SeedingCutShort) {
                            restartRequired = new Error(
                                `The seeding stage of run ${runId} was cut short and its connections were destroyed, so a write it sent may still land in the next card. Restart the runner, then run the card again.`
                            )
                        }
                        throw error
                    }
                )
                await judge.open(seeded)
                const exitsBefore = environment.exits().length
                stopHealth = watchHealth(environment)
                sampler = await startSampler(
                    CdpRole.options.map((role) => ({ role, metricsUrl: environment.role(role).metricsUrl }))
                )
                await valves.start(card.valves, { environment, probe, teams: seeded.teamIds })
                const sesFeedback = await watchSesFeedback({
                    edgeUrl,
                    lag: () => environment.groupLag(SES_WEBHOOKS_GROUP),
                })
                const units = await drive(loaded, seeded, judge, signal, {
                    producer,
                    eventsTopic,
                    cdpApi,
                    sesFeedback,
                    runId,
                })
                await valves.releaseAll()
                const convergence = await judge.converge(durationMs(card.convergeWithin), signal)
                sampled = await sampler.stop()
                const down = await stopHealth()
                const invariants = await judge.check(card.invariants, card.gates)
                const measurements = measure(card.measure, {
                    ...judge.evidence(),
                    ...sampled,
                    sampledFrom: sampler.sampledFrom,
                })
                const verdict = statusOf({
                    minOffered: card.drive.minOffered,
                    units,
                    down,
                    convergence,
                    invariants,
                    timeline: valves.timeline(),
                    exits: environment.exits().slice(exitsBefore),
                })
                outcome = { ...verdict, units, convergence, invariants, measurements }
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
                sampled = (await sampler?.stop()) ?? sampled
                try {
                    await producer?.disconnect()
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
