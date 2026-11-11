import { randomUUID } from 'crypto'
import { createReadStream, createWriteStream, existsSync, mkdirSync, statSync, writeFileSync } from 'fs'
import path from 'path'
import { pipeline } from 'stream/promises'
import { setTimeout as sleep } from 'timers/promises'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PostgresRouter } from '~/common/utils/db/postgres'

import { CdpRole, LoadedCard } from '../cards'
import { durationMs } from '../duration'
import { EDGE_URL, Environment, defaultStateDir } from '../environment/environment'
import { consumerGroupsOf, roleSpecs, secretsOf } from '../environment/roles'
import { STACK, cyclotronUrlOf } from '../environment/stack'
import { DriveSummary, drive, seed } from '../generator/generator'
import { Convergence, InvariantResult, Judge, createJudge } from '../judge/judge'
import { createCyclotronProbe } from '../probe/cyclotron-probe'
import { Status, statusOf } from './status'

export type RunResult = {
    runId: string
    status: Status
    statusReason: string
    recorded: boolean
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

type Outcome = Pick<RunResult, 'status' | 'statusReason' | 'units' | 'convergence' | 'invariants'>

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
    const files = CdpRole.options.map((role) => path.join(stateDir, `${role}.log`))
    const offsets = files.map((file) => (existsSync(file) ? statSync(file).size : 0))
    return async (evidenceDir) => {
        mkdirSync(path.join(evidenceDir, 'logs'), { recursive: true })
        for (const [i, file] of files.entries()) {
            const tail = path.join(evidenceDir, 'logs', path.basename(file))
            const size = existsSync(file) ? statSync(file).size : 0
            if (size > offsets[i]) {
                await pipeline(createReadStream(file, { start: offsets[i], end: size - 1 }), createWriteStream(tail))
            } else {
                writeFileSync(tail, '')
            }
        }
    }
}

function writeEvidence(result: RunResult, judge: Judge): void {
    const { journal, truth } = judge.evidence()
    writeFileSync(path.join(result.evidenceDir, 'journal.json'), JSON.stringify(journal, null, 2))
    writeFileSync(path.join(result.evidenceDir, 'truth.json'), JSON.stringify(truth, null, 2))
    writeFileSync(path.join(result.evidenceDir, 'scorecard.json'), JSON.stringify(result, null, 2))
}

export function createRunner(environment: Environment, env: NodeJS.ProcessEnv = process.env): Runner {
    const stateDir = defaultStateDir(env)
    let producer: KafkaProducerWrapper | undefined

    return {
        async up() {
            await environment.up()
        },

        async run(loaded, signal) {
            const { card, profile } = loaded
            const runId = randomUUID()
            const startedAt = new Date().toISOString()
            const evidenceDir = path.join(stateDir, runId)
            const writeLogTails = keepLogTails(stateDir)
            const specs = roleSpecs(env, EDGE_URL, secretsOf(env), profile.settings)
            const [
                {
                    topics: [eventsTopic],
                },
            ] = consumerGroupsOf(specs)
            const judge = createJudge({ edgeUrl: EDGE_URL, probe: createCyclotronProbe(cyclotronUrlOf(specs[0])) })
            const postgres = new PostgresRouter(
                {
                    DATABASE_URL: specs[0].env.DATABASE_URL || STACK.postgresUrl,
                    POSTGRES_CONNECTION_POOL_SIZE: 2,
                },
                'posthog-scenarios'
            )
            let outcome: Outcome = { status: 'invalid', statusReason: 'not started', invariants: [] }
            let stopHealth: (() => Promise<string[]>) | undefined
            try {
                await environment.reset(profile.settings)
                const seeded = await seed(loaded, postgres)
                await judge.open(seeded)
                producer ??= await KafkaProducerWrapper.create(undefined)
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
                await postgres.end()
            }
            const result: RunResult = {
                runId,
                ...outcome,
                recorded: false,
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
            try {
                await writeLogTails(evidenceDir)
                writeEvidence(result, judge)
                return result
            } catch (error) {
                return {
                    ...result,
                    status: 'invalid',
                    statusReason: `${result.statusReason}; the evidence could not be written: ${(error as Error).message}`,
                }
            }
        },

        async down() {
            try {
                await producer?.disconnect()
            } finally {
                producer = undefined
                await environment.down()
            }
        },
    }
}
