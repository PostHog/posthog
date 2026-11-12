import { randomUUID } from 'crypto'
import { createReadStream, createWriteStream, existsSync, mkdirSync, statSync, writeFileSync } from 'fs'
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
import { consumerGroupsOf, fetchRetriesOf, roleSpecs, secretsOf } from '../environment/roles'
import { STACK, cyclotronUrlOf } from '../environment/stack'
import { DriveSummary, drive, seed } from '../generator/generator'
import { Convergence, InvariantResult, createJudge } from '../judge/judge'
import { Measurement, Sampled, Sampler, measure, startSampler } from '../judge/measurements'
import { createCyclotronProbe } from '../probe/cyclotron-probe'
import { provenanceOf } from '../scorecard/provenance'
import { scorecardOf } from '../scorecard/scorecard'
import { publish } from '../scorecard/write'
import { ValveTimelineEntry, createValves } from '../valves/valves'
import { Status, statusOf } from './status'

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

type Outcome = Pick<RunResult, 'status' | 'statusReason' | 'units' | 'convergence' | 'invariants' | 'measurements'>

function producerConfigOf(env: NodeJS.ProcessEnv): ProducerGlobalConfig {
    const settings = Object.entries(env).flatMap(([key, value]) =>
        key.startsWith(LOAD_PRODUCER_SETTING_PREFIX) && value
            ? [[key.slice(LOAD_PRODUCER_SETTING_PREFIX.length).replace(/_/g, '.').toLowerCase(), value]]
            : []
    )
    return { 'message.timeout.ms': DELIVERY_TIMEOUT_MS, ...Object.fromEntries(settings) }
}

function watchHealth(environment: Environment): () => Promise<string[]> {
    const down = new Set<string>()
    const stopped = new AbortController()
    const watching = (async () => {
        while (!stopped.signal.aborted) {
            const health = await environment.health().catch(() => ({ down: ['health check'] }))
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
    writeFileSync(path.join(evidenceDir, name), JSON.stringify(value, null, 2))
}

async function errorOf(write: () => Promise<void> | void): Promise<string | undefined> {
    try {
        await write()
        return undefined
    } catch (error) {
        return (error as Error).message
    }
}

function withEvidenceError(result: RunResult, error: string | undefined): RunResult {
    return error === undefined
        ? result
        : {
              ...result,
              status: 'invalid',
              statusReason: `${result.statusReason}; the evidence could not be written: ${error}`,
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
            const postgres = new PostgresRouter(
                {
                    DATABASE_URL: specs[0].env.DATABASE_URL || STACK.postgresUrl,
                    POSTGRES_CONNECTION_POOL_SIZE: 2,
                },
                'posthog-scenarios'
            )
            let outcome: Outcome = { status: 'invalid', statusReason: 'not started', invariants: [], measurements: [] }
            let stopHealth: (() => Promise<string[]>) | undefined
            let sampler: Sampler | undefined
            let sampled: Sampled = { samples: [], missed: [] }
            let producer: KafkaProducerWrapper | undefined
            try {
                producer = await KafkaProducerWrapper.createWithConfig(undefined, producerConfigOf(specs[0].env))
                await environment.reset(profile.settings).catch((error: unknown) => {
                    restartRequired = new Error(
                        `The reset before run ${runId} failed and stopped the environment: ${(error as Error).message}. Restart the runner, then run the card again.`
                    )
                    throw error
                })
                const seeded = await seed(loaded, postgres)
                await judge.open(seeded)
                const exitsBefore = environment.exits().length
                stopHealth = watchHealth(environment)
                sampler = await startSampler(
                    CdpRole.options.map((role) => ({ role, metricsUrl: environment.role(role).metricsUrl }))
                )
                await valves.start(card.valves, { environment, probe, teams: seeded.teamIds })
                const units = await drive(loaded, seeded, judge, signal, { producer, eventsTopic, cdpApi, runId })
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
                    statusReason: `the run stopped: ${(error as Error).message}`,
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
                    const failed = `the load producer did not disconnect: ${(error as Error).message}`
                    outcome = {
                        ...outcome,
                        status: 'invalid',
                        statusReason: outcome.status === 'passed' ? failed : `${outcome.statusReason}; ${failed}`,
                    }
                } finally {
                    await postgres.end()
                }
            }
            const base: RunResult = {
                runId,
                ...outcome,
                recorded: false,
                cardId: card.id,
                cardHash: loaded.cardHash,
                profileHash: loaded.profileHash,
                origin: 'local-agent',
                timeline: valves.timeline(),
                startedAt,
                endedAt: new Date().toISOString(),
                evidenceDir,
            }
            const evidenceError = await errorOf(async () => {
                await writeLogTails(evidenceDir)
                const { journal, truth } = judge.evidence()
                writeJson(evidenceDir, 'journal.json', journal)
                writeJson(evidenceDir, 'truth.json', truth)
                writeJson(evidenceDir, 'metrics.json', sampled)
            })
            const judged = withEvidenceError(base, evidenceError)
            const event = scorecardOf(judged, loaded, provenanceOf())
            const written = await publish(event, env, signal)
            const result: RunResult = {
                ...judged,
                recorded: written.recorded,
                captured: written.captured,
                scorecardError: written.problem,
            }
            const filesError =
                evidenceError === undefined
                    ? await errorOf(() => {
                          writeJson(evidenceDir, 'scorecard-event.json', event)
                          writeJson(evidenceDir, 'scorecard.json', result)
                      })
                    : undefined
            if (filesError === undefined) {
                return result
            }
            const problems = [written.problem, `the scorecard files could not be written: ${filesError}`]
            return { ...result, scorecardError: problems.filter((problem) => problem !== undefined).join('; ') }
        },

        async down() {
            await environment.down()
        },
    }
}
