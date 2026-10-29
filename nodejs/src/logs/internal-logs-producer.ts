import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { sanitizeForUTF8 } from '~/common/utils/strings'
import type { TeamManager } from '~/common/utils/team-manager'
import { delay } from '~/common/utils/utils'
import type { ValueMatcher } from '~/types'

import type { LogsIngestionConsumerConfig } from './config'
import { INTERNAL_LOGS_HTTP_HEADER, INTERNAL_SOURCE_POLICIES, signInternalLogs } from './internal-logs'

const SERVICE_NAMES: Readonly<Record<string, string>> = {
    hog_flow: 'posthog-internal-workflows',
}

const SEVERITY_NUMBERS: Readonly<Record<string, number>> = { debug: 5, info: 9, warn: 13, error: 17 }

// Half of capture-logs' default 2 MiB body limit, which leaves room for the envelope.
const MAX_REQUEST_RECORD_BYTES = 1024 * 1024

// A JSON-escaped character takes at most 6 bytes, so a message cut to this length always fits in one request.
const MAX_MESSAGE_LENGTH = 128 * 1024

export type InternalLogEntry = {
    team_id: number
    log_source_id: string
    instance_id: string
    timestamp: DateTime
    level: string
    message: string
}

export type InternalLogsProducerConfig = Pick<
    LogsIngestionConsumerConfig,
    | 'LOGS_INTERNAL_INGESTION_SIGNING_KEYS'
    | 'LOGS_INTERNAL_PRODUCER_URL'
    | 'LOGS_INTERNAL_PRODUCER_TEAMS'
    | 'LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT'
    | 'LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES'
    | 'LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS'
>

type QueuedBatch = { source: string; teamId: number; records: OtlpLogRecord[] }

type Chunk = { records: OtlpLogRecord[]; bytes: number }

type BufferedRequest = Chunk & { source: string; teamId: number; settled: () => void }

type AttemptResult = { outcome: 'sent' | 'rejected' | 'retry'; detail: string }

const RETRY_BASE_DELAY_MS = 100
const RETRY_MAX_DELAY_MS = 5_000

const internalLogsProducerBatchesCounter = new Counter({
    name: 'logs_internal_producer_batches_total',
    help: 'Signed internal logs batches sent to capture-logs, by source and outcome. Only a sent batch reaches the logs product.',
    labelNames: ['source', 'outcome'],
})

/**
 * Delivery runs in the background, so a slow or down capture-logs never slows the caller. A batch is lost only when
 * the buffer is full, its retries time out, capture-logs rejects it, or the process stops before `drain` completes.
 */
export class InternalLogsProducer {
    private readonly enabled: boolean
    private readonly isTeamEnabled: ValueMatcher<number>
    private queued = new Map<string, QueuedBatch>()
    private pending: BufferedRequest[] = []
    // Counts in-flight requests as well as pending ones, because a request that retries keeps its records in memory.
    private bufferedBytes = 0
    private inFlight = new Set<BufferedRequest[]>()
    private idleWaiters: (() => void)[] = []

    constructor(
        private readonly config: InternalLogsProducerConfig,
        private readonly teamManager: Pick<TeamManager, 'getTeam'>
    ) {
        this.enabled =
            config.LOGS_INTERNAL_PRODUCER_URL.length > 0 &&
            config.LOGS_INTERNAL_INGESTION_SIGNING_KEYS.trim().length > 0
        this.isTeamEnabled = buildIntegerMatcher(config.LOGS_INTERNAL_PRODUCER_TEAMS, true)
    }

    enqueue(source: string, entries: InternalLogEntry[]): void {
        if (
            !this.enabled ||
            !Object.hasOwn(INTERNAL_SOURCE_POLICIES, source) ||
            !Object.hasOwn(SERVICE_NAMES, source)
        ) {
            return
        }
        for (const entry of entries) {
            if (!this.isTeamEnabled(entry.team_id)) {
                continue
            }
            const key = `${source}:${entry.team_id}`
            const batch = this.queued.get(key) ?? { source, teamId: entry.team_id, records: [] }
            batch.records.push(toOtlpLogRecord(entry))
            this.queued.set(key, batch)
        }
    }

    /** Resolves when every batch from this flush is sent or given up on. Never throws. */
    flush(): Promise<void> {
        const batches = [...this.queued.values()]
        this.queued = new Map()
        const settled = batches.flatMap(({ source, teamId, records }) =>
            splitBySize(records).map((chunk) => this.buffer(source, teamId, chunk))
        )
        this.pump()
        return Promise.all(settled).then(() => undefined)
    }

    /** Flushes, then waits until every buffered batch settles or the timeout passes. Call on shutdown. */
    async drain(timeoutMs: number): Promise<void> {
        void this.flush()
        if (this.isIdle()) {
            return
        }
        let timer: NodeJS.Timeout | undefined
        const idle = new Promise<boolean>((resolve) => this.idleWaiters.push(() => resolve(true)))
        const timeout = new Promise<boolean>((resolve) => {
            timer = setTimeout(() => resolve(false), timeoutMs)
        })
        const drained = await Promise.race([idle, timeout])
        clearTimeout(timer)
        if (!drained) {
            for (const { source } of [...this.pending, ...[...this.inFlight].flat()]) {
                internalLogsProducerBatchesCounter.inc({ source, outcome: 'abandoned' })
            }
            logger.warn('Internal logs producer stopped before all batches were sent', {
                pending: this.pending.length,
                inFlight: this.inFlight.size,
            })
        }
    }

    private buffer(source: string, teamId: number, chunk: Chunk): Promise<void> {
        if (this.bufferedBytes + chunk.bytes > this.config.LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES) {
            internalLogsProducerBatchesCounter.inc({ source, outcome: 'dropped' })
            return Promise.resolve()
        }
        this.bufferedBytes += chunk.bytes
        return new Promise((settled) => this.pending.push({ ...chunk, source, teamId, settled }))
    }

    private pump(): void {
        while (this.inFlight.size < this.config.LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT && this.pending.length > 0) {
            const batches = this.takeRequest()
            this.inFlight.add(batches)
            void this.deliver(batches).finally(() => {
                this.inFlight.delete(batches)
                for (const batch of batches) {
                    this.bufferedBytes -= batch.bytes
                    batch.settled()
                }
                this.pump()
                if (this.isIdle()) {
                    this.idleWaiters.splice(0).forEach((resolve) => resolve())
                }
            })
        }
    }

    /**
     * Takes the oldest batch plus the queued batches for the same team, up to one request. A backlog after an outage
     * then leaves in a few large requests, because one request per batch cannot catch up while new batches arrive.
     */
    private takeRequest(): BufferedRequest[] {
        const first = this.pending.shift()!
        const batches = [first]
        let bytes = first.bytes
        this.pending = this.pending.filter((batch) => {
            if (
                batch.source !== first.source ||
                batch.teamId !== first.teamId ||
                bytes + batch.bytes > MAX_REQUEST_RECORD_BYTES
            ) {
                return true
            }
            batches.push(batch)
            bytes += batch.bytes
            return false
        })
        return batches
    }

    private isIdle(): boolean {
        return this.inFlight.size === 0 && this.pending.length === 0
    }

    private async deliver(batches: BufferedRequest[]): Promise<void> {
        const [{ source, teamId }] = batches
        // Counts batches, not requests, so that every outcome uses the same unit as `dropped`.
        const count = (outcome: string): void =>
            internalLogsProducerBatchesCounter.inc({ source, outcome }, batches.length)
        const deadline = Date.now() + this.config.LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS
        const body = JSON.stringify(
            toOtlpJson(
                source,
                batches.flatMap((batch) => batch.records)
            )
        )
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                count('unknown_team')
                return
            }
            for (let attempt = 0; ; attempt++) {
                const result = await this.attempt(source, teamId, team.api_token, body)
                if (result.outcome !== 'retry') {
                    count(result.outcome)
                    if (result.outcome === 'rejected') {
                        logger.warn('Internal logs batch rejected by capture-logs', {
                            source,
                            teamId,
                            status: result.detail,
                        })
                    }
                    return
                }
                const wait = Math.random() * Math.min(RETRY_MAX_DELAY_MS, RETRY_BASE_DELAY_MS * 2 ** attempt)
                if (Date.now() + wait > deadline) {
                    count('failed')
                    logger.warn('Internal logs batch failed after retries', {
                        source,
                        teamId,
                        attempts: attempt + 1,
                        last: result.detail,
                    })
                    return
                }
                await delay(wait)
            }
        } catch (error) {
            count('failed')
            logger.warn('Internal logs batch failed', { source, teamId, error: String(error) })
        }
    }

    private async attempt(source: string, teamId: number, token: string, body: string): Promise<AttemptResult> {
        try {
            const response = await internalFetch(this.config.LOGS_INTERNAL_PRODUCER_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
                    [INTERNAL_LOGS_HTTP_HEADER]: signInternalLogs(
                        this.config.LOGS_INTERNAL_INGESTION_SIGNING_KEYS,
                        source,
                        teamId
                    ),
                },
                body,
            })
            await response.dump()
            const { status } = response
            if (status >= 200 && status < 300) {
                return { outcome: 'sent', detail: String(status) }
            }
            // Any other 4xx is a bad request, which fails the same way on every attempt.
            const retriable = status >= 500 || status === 408 || status === 429
            return { outcome: retriable ? 'retry' : 'rejected', detail: String(status) }
        } catch (error) {
            return { outcome: 'retry', detail: String(error) }
        }
    }
}

type OtlpLogRecord = Record<string, unknown>

function toOtlpLogRecord(entry: InternalLogEntry): OtlpLogRecord {
    return {
        timeUnixNano: (BigInt(entry.timestamp.toMillis()) * 1_000_000n).toString(),
        severityText: entry.level.toUpperCase(),
        severityNumber: SEVERITY_NUMBERS[entry.level] ?? 0,
        // capture-logs rejects a whole request that holds one unpaired surrogate. The cut can split a pair, so sanitize after it.
        body: { stringValue: sanitizeForUTF8(entry.message.slice(0, MAX_MESSAGE_LENGTH)) },
        attributes: [
            { key: 'log_source_id', value: { stringValue: entry.log_source_id } },
            { key: 'instance_id', value: { stringValue: entry.instance_id } },
        ],
    }
}

function splitBySize(records: OtlpLogRecord[]): Chunk[] {
    const chunks: Chunk[] = []
    let chunk: OtlpLogRecord[] = []
    let chunkBytes = 0
    for (const record of records) {
        const bytes = Buffer.byteLength(JSON.stringify(record))
        if (chunk.length > 0 && chunkBytes + bytes > MAX_REQUEST_RECORD_BYTES) {
            chunks.push({ records: chunk, bytes: chunkBytes })
            chunk = []
            chunkBytes = 0
        }
        chunk.push(record)
        chunkBytes += bytes
    }
    if (chunk.length > 0) {
        chunks.push({ records: chunk, bytes: chunkBytes })
    }
    return chunks
}

function toOtlpJson(source: string, records: OtlpLogRecord[]): Record<string, unknown> {
    return {
        resourceLogs: [
            {
                resource: {
                    attributes: [{ key: 'service.name', value: { stringValue: SERVICE_NAMES[source] } }],
                },
                scopeLogs: [
                    {
                        scope: { name: source },
                        logRecords: records,
                    },
                ],
            },
        ],
    }
}
