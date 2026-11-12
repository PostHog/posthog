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
import { Client } from 'pg'
import { pipeline } from 'stream/promises'
import { setTimeout as sleep } from 'timers/promises'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PostgresRouter } from '~/common/utils/db/postgres'

import { CdpRole, LOAD_PRODUCER_SETTING_PREFIX, LoadedCard } from '../cards'
import { durationMs } from '../duration'
import { Environment, defaultStateDir } from '../environment/environment'
import { RoleSpec, consumerGroupsOf, roleSpecs, secretsOf } from '../environment/roles'
import { cyclotronUrlOf, postgresUrlOf } from '../environment/stack'
import { DriveSummary, SeedState, drive, seed } from '../generator/generator'
import { Convergence, InvariantResult, createJudge } from '../judge/judge'
import { createCyclotronProbe } from '../probe/cyclotron-probe'
import { provenanceOf } from '../scorecard/provenance'
import { scorecardOf } from '../scorecard/scorecard'
import { publish } from '../scorecard/write'
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
    measurements: never[]
    timeline: never[]
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

type Outcome = Pick<RunResult, 'status' | 'statusReason' | 'units' | 'convergence' | 'invariants'>

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
        return (error as Error).message
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

async function connectWithin(databaseUrl: string, withinMs: number, signal: AbortSignal): Promise<void> {
    signal.throwIfAborted()
    const client = new Client({ connectionString: databaseUrl, connectionTimeoutMillis: withinMs })
    let cancel = (): void => undefined
    const aborted = new Promise<never>((_, reject) => {
        cancel = () => {
            void client.end().catch(() => undefined)
            reject(signal.reason)
        }
        signal.addEventListener('abort', cancel, { once: true })
    })
    try {
        await Promise.race([client.connect(), aborted])
    } catch (error) {
        signal.throwIfAborted()
        throw new Error(
            `the seeding database did not finish connecting within ${withinMs} ms: ${(error as Error).message}`
        )
    } finally {
        signal.removeEventListener('abort', cancel)
    }
    await client.end()
}

async function closedWithin(postgres: PostgresRouter | undefined, withinMs: number): Promise<boolean> {
    return (
        postgres === undefined ||
        (await Promise.race([
            postgres.end().then(
                () => true,
                () => true
            ),
            sleep(withinMs, false, { ref: false }),
        ]))
    )
}

async function seedWithin(
    loaded: LoadedCard,
    postgres: PostgresRouter,
    signal: AbortSignal,
    withinMs: number
): Promise<SeedState> {
    const deadline = AbortSignal.timeout(withinMs)
    const stop = AbortSignal.any([signal, deadline])
    let onStop = (): void => undefined
    const stopped = new Promise<never>((_, reject) => {
        onStop = () =>
            reject(deadline.aborted ? new Error(`seeding did not finish within ${withinMs} ms`) : stop.reason)
        stop.addEventListener('abort', onStop, { once: true })
    })
    try {
        return await Promise.race([seed(loaded, postgres, stop), stopped])
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
            const specs = roleSpecs(env, edgeUrl, secretsOf(env), stateDir, profile.settings)
            const [
                {
                    topics: [eventsTopic],
                },
            ] = consumerGroupsOf(specs)
            const judge = createJudge({ edgeUrl, probe: createCyclotronProbe(cyclotronUrlOf(specs[0])) })
            let outcome: Outcome = { status: 'invalid', statusReason: 'not started', invariants: [] }
            let stopHealth: (() => Promise<string[]>) | undefined
            let producer: KafkaProducerWrapper | undefined
            let postgres: PostgresRouter | undefined
            try {
                producer = await KafkaProducerWrapper.createWithConfig(undefined, producerConfigOf(specs[0].env))
                await environment.reset(profile.settings).catch((error: unknown) => {
                    restartRequired = new Error(
                        `The reset before run ${runId} failed and stopped the environment: ${(error as Error).message}. Restart the runner, then run the card again.`
                    )
                    throw error
                })
                const seedingUrl = seedingUrlOf(specs[0])
                await connectWithin(seedingUrl, seedWithinMs, signal)
                postgres = new PostgresRouter(
                    { DATABASE_URL: seedingUrl, POSTGRES_CONNECTION_POOL_SIZE: 2 },
                    'posthog-scenarios'
                )
                const seeded = await seedWithin(loaded, postgres, signal, seedWithinMs)
                await judge.open(seeded)
                stopHealth = watchHealth(environment)
                const units = await drive(loaded, seeded, judge, signal, { producer, eventsTopic, runId })
                const convergence = await judge.converge(durationMs(card.convergeWithin), signal)
                const down = await stopHealth()
                const invariants = await judge.check(card.invariants, card.gates)
                const verdict = statusOf({ minOffered: card.drive.minOffered, units, down, convergence, invariants })
                outcome = { ...verdict, units, convergence, invariants }
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
                await stopHealth?.()
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
                }
                if (!(await closedWithin(postgres, seedWithinMs))) {
                    restartRequired = new Error(
                        `The seeding connections of run ${runId} did not close and may still write fixtures into the next card. Restart the runner, then run the card again.`
                    )
                    const failed = `the seeding connections did not close within ${seedWithinMs} ms`
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
                measurements: [],
                timeline: [],
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
