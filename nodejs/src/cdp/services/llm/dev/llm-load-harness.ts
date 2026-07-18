/**
 * Load harness for the LLM step's executor + wake path. Parks N jobs in a real cyclotron_jobs table,
 * then drives them through the executor at a target concurrency with a fake gateway (configurable
 * latency + response size), and reports the RFC's scale invariants:
 *
 *   - wake works at scale (all jobs woken), and is a cheap single-row update
 *   - throughput ≈ concurrency / call-duration (Little's law) - the fleet is I/O-bound
 *   - cyclotron_jobs.state stays small even for large outputs, because the spill keeps only a ref
 *
 * It does NOT need Kafka, the workflow-worker fleet, or a real gateway - it isolates the parts that
 * live in this service. Run against a local cyclotron DB:
 *
 *   JOBS=5000 CONCURRENCY=200 RESPONSE_BYTES=20000 GATEWAY_LATENCY_MS=300 \
 *     pnpm --filter=@posthog/nodejs llm:loadtest
 *
 * This file lives under dev/ so the test runner ignores it.
 */
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2Manager } from '../../cyclotron-v2/manager'
import { InMemoryLlmBlobStore } from '../llm-blob-store'
import { executeLlmRequest } from '../llm-executor-core'
import { LlmGatewayClient } from '../llm-gateway.client'
import { LlmStepRequest } from '../llm-step.types'

const JOBS = Number(process.env.JOBS ?? 2000)
const CONCURRENCY = Number(process.env.CONCURRENCY ?? 200)
const RESPONSE_BYTES = Number(process.env.RESPONSE_BYTES ?? 20_000)
const GATEWAY_LATENCY_MS = Number(process.env.GATEWAY_LATENCY_MS ?? 300)
const SPILL = (process.env.SPILL ?? '1') === '1'
const DB_URL = process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/cyclotron_node'

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

// A fake gateway: waits GATEWAY_LATENCY_MS (standing in for the model call the executor holds open),
// then returns a completion of RESPONSE_BYTES so we can watch the spill keep state small.
const fakeGateway: LlmGatewayClient = {
    async complete(): Promise<{ text: string; model: string }> {
        await sleep(GATEWAY_LATENCY_MS)
        return { text: 'x'.repeat(RESPONSE_BYTES), model: 'fake/model' }
    },
}

function parkedStateBuffer(actionId: string, nonce: string): Buffer {
    return Buffer.from(
        JSON.stringify({
            state: {
                event: {},
                actionStepCount: 1,
                currentAction: { id: actionId, startedAtTimestamp: 0, llmRequestId: nonce },
            },
        })
    )
}

// Runs `worker` over `items` with at most `concurrency` in flight.
async function pool<T>(items: T[], concurrency: number, worker: (item: T) => Promise<void>): Promise<void> {
    let next = 0
    const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
        while (next < items.length) {
            const i = next++
            await worker(items[i])
        }
    })
    await Promise.all(runners)
}

function percentile(sorted: number[], p: number): number {
    if (sorted.length === 0) {
        return 0
    }
    return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))]
}

async function main(): Promise<void> {
    const pg = new Pool({ connectionString: DB_URL, max: CONCURRENCY + 5 })
    try {
        await pg.query('SELECT 1 FROM cyclotron_jobs LIMIT 1')
    } catch (err) {
        // eslint-disable-next-line no-console
        console.error(`Cannot reach cyclotron DB at ${DB_URL}: ${String(err)}. Start the stack first.`)
        process.exit(1)
    }

    const blobStore = SPILL ? new InMemoryLlmBlobStore() : undefined
    const runId = uuidv7()
    const nonce = 'n1'

    const manager = new CyclotronV2Manager({
        pool: { dbUrl: DB_URL },
        depthLimit: 100_000_000,
        depthCheckIntervalMs: 0,
    })
    await manager.connect()

    // eslint-disable-next-line no-console
    console.log(
        `Seeding ${JOBS} parked jobs (concurrency ${CONCURRENCY}, response ${RESPONSE_BYTES}B, spill ${SPILL})...`
    )
    await pg.query(`DELETE FROM cyclotron_jobs WHERE queue_name = 'llm-loadtest'`)

    const requests: LlmStepRequest[] = []
    await pool(
        Array.from({ length: JOBS }, (_, i) => i),
        50,
        async (i) => {
            const actionId = `a-${i}`
            const jobId = await manager.createJob({
                teamId: 1,
                queueName: 'llm-loadtest',
                functionId: runId,
                actionId,
                state: parkedStateBuffer(actionId, nonce),
                scheduled: new Date(Date.now() + 60 * 60 * 1000),
            })
            requests.push({
                jobId,
                teamId: 1,
                hogFlowId: runId,
                actionId,
                nonce,
                model: 'fake/model',
                messages: [{ role: 'user', content: 'hi' }],
            })
        }
    )
    await manager.disconnect()

    // eslint-disable-next-line no-console
    console.log(`Driving ${JOBS} requests through the executor...`)
    const latencies: number[] = []
    const outcomes: Record<string, number> = {}
    const startedAt = Date.now()

    await pool(requests, CONCURRENCY, async (request) => {
        const t0 = Date.now()
        const { outcome } = await executeLlmRequest({ request, gatewayClient: fakeGateway, pool: pg, blobStore })
        latencies.push(Date.now() - t0)
        outcomes[outcome] = (outcomes[outcome] ?? 0) + 1
    })

    const wallMs = Date.now() - startedAt
    latencies.sort((a, b) => a - b)

    const sizes = await pg.query<{ max: string; avg: string }>(
        `SELECT max(length(state)) AS max, avg(length(state))::int AS avg FROM cyclotron_jobs WHERE queue_name = 'llm-loadtest'`
    )
    const maxState = Number(sizes.rows[0]?.max ?? 0)
    const avgState = Number(sizes.rows[0]?.avg ?? 0)

    // eslint-disable-next-line no-console
    console.log('\n──────── LLM step load result ────────')
    // eslint-disable-next-line no-console
    console.table({
        jobs: JOBS,
        concurrency: CONCURRENCY,
        wall_seconds: (wallMs / 1000).toFixed(1),
        throughput_per_sec: Math.round((JOBS / wallMs) * 1000),
        wake_p50_ms: percentile(latencies, 50),
        wake_p99_ms: percentile(latencies, 99),
        state_max_bytes: maxState,
        state_avg_bytes: avgState,
        response_bytes: RESPONSE_BYTES,
        outcomes: JSON.stringify(outcomes),
    })

    // Invariant checks - the RFC claims this harness proves.
    const allWoken = outcomes.woken === JOBS
    const stateStaysSmall = !SPILL || maxState < 5120 // spilled: only a ref lands in state
    // eslint-disable-next-line no-console
    console.log(`\nall jobs woken: ${allWoken ? 'PASS' : `FAIL (${JSON.stringify(outcomes)})`}`)
    // eslint-disable-next-line no-console
    console.log(
        `state stays small under spill: ${stateStaysSmall ? 'PASS' : `FAIL (max ${maxState}B for ${RESPONSE_BYTES}B responses)`}`
    )

    await pg.query(`DELETE FROM cyclotron_jobs WHERE queue_name = 'llm-loadtest'`)
    await pg.end()
    process.exit(allWoken && stateStaysSmall ? 0 : 1)
}

void main()
