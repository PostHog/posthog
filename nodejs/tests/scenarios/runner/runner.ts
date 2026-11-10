import { randomUUID } from 'crypto'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'fs'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { getDefaultCdpConfig } from '~/cdp/config'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PostgresRouter } from '~/common/utils/db/postgres'

import { CdpRole, LoadedCard } from '../cards'
import { durationMs } from '../duration'
import { EDGE_URL, Environment, defaultStateDir } from '../environment/environment'
import { STACK } from '../environment/stack'
import { DriveSummary, drive, seed } from '../generator/generator'
import { Convergence, InvariantResult, Judge, Measurement, createJudge } from '../judge/judge'
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
    measurements: Measurement[]
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

type Outcome = Pick<RunResult, 'status' | 'statusReason' | 'units' | 'convergence' | 'invariants' | 'measurements'>

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

function keepLogTails(stateDir: string): (evidenceDir: string) => void {
    const files = CdpRole.options.map((role) => path.join(stateDir, `${role}.log`))
    const sizes = files.map((file) => (existsSync(file) ? statSync(file).size : 0))
    return (evidenceDir) => {
        mkdirSync(path.join(evidenceDir, 'logs'), { recursive: true })
        files.forEach((file, i) =>
            writeFileSync(
                path.join(evidenceDir, 'logs', path.basename(file)),
                existsSync(file) ? readFileSync(file).subarray(sizes[i]) : ''
            )
        )
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
    const probe = createCyclotronProbe(env.CYCLOTRON_NODE_DATABASE_URL || STACK.cyclotronNodeUrl)
    let postgres: PostgresRouter | undefined
    let producer: KafkaProducerWrapper | undefined

    return {
        async up() {
            await environment.up()
            postgres = new PostgresRouter(
                { DATABASE_URL: env.DATABASE_URL || STACK.postgresUrl, POSTGRES_CONNECTION_POOL_SIZE: 2 },
                'posthog-scenarios'
            )
            producer = await KafkaProducerWrapper.create(undefined)
        },

        async run(loaded, signal) {
            if (!postgres || !producer) {
                throw new Error('Start the runner with up() before run().')
            }
            const { card, profile } = loaded
            const runId = randomUUID()
            const startedAt = new Date().toISOString()
            const evidenceDir = path.join(stateDir, runId)
            mkdirSync(evidenceDir, { recursive: true })
            const writeLogTails = keepLogTails(stateDir)
            const judge = createJudge({ edgeUrl: EDGE_URL, probe })
            const eventsTopic =
                profile.settings.CDP_EVENTS_CONSUMER_TOPIC ||
                env.CDP_EVENTS_CONSUMER_TOPIC ||
                getDefaultCdpConfig().CDP_EVENTS_CONSUMER_TOPIC
            let outcome: Outcome = { status: 'invalid', statusReason: 'not started', invariants: [], measurements: [] }
            let stopHealth: (() => Promise<string[]>) | undefined
            try {
                await environment.reset(profile.settings)
                const seeded = await seed(loaded, postgres)
                await judge.open(seeded)
                stopHealth = watchHealth(environment)
                const units = await drive(loaded, seeded, judge, signal, { producer, eventsTopic, runId })
                const convergence = await judge.converge(durationMs(card.convergeWithin), signal)
                const down = await stopHealth()
                const invariants = await judge.check(card.invariants, card.gates)
                const measurements = await judge.measure(card.measure)
                const verdict = statusOf({ minOffered: card.drive.minOffered, units, down, convergence, invariants })
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
                await stopHealth?.()
            }
            const result: RunResult = {
                runId,
                ...outcome,
                recorded: false,
                cardId: card.id,
                cardHash: loaded.cardHash,
                profileHash: loaded.profileHash,
                origin: 'local-agent',
                timeline: [],
                startedAt,
                endedAt: new Date().toISOString(),
                evidenceDir,
            }
            writeLogTails(evidenceDir)
            writeEvidence(result, judge)
            return result
        },

        async down() {
            try {
                await producer?.disconnect()
                await postgres?.end()
            } finally {
                producer = undefined
                postgres = undefined
                await environment.down()
            }
        },
    }
}
