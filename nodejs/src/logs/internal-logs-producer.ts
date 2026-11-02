import { DateTime } from 'luxon'
import { Counter, Gauge } from 'prom-client'

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

type Batch = { source: string; teamId: number; records: string[] }

type Request = Batch & { bytes: number }

type AttemptResult = { outcome: 'sent' | 'rejected' | 'unknown_team' | 'retry'; detail: string }

const RETRY_BASE_DELAY_MS = 100
const RETRY_MAX_DELAY_MS = 5_000
const DRAIN_POLL_MS = 50

const internalLogsProducerRecordsCounter = new Counter({
    name: 'logs_internal_producer_records_total',
    help: 'Internal log records sent to capture-logs, by source and outcome. Only a sent record reaches the logs product.',
    labelNames: ['source', 'outcome'],
})

const internalLogsProducerBufferedBytesGauge = new Gauge({
    name: 'logs_internal_producer_buffered_bytes',
    help: 'Bytes of internal log records a producer holds in memory, queued, waiting or in flight.',
})

const internalLogsProducerInFlightGauge = new Gauge({
    name: 'logs_internal_producer_in_flight_requests',
    help: 'Requests a producer has open to capture-logs.',
})

function countRecords(source: string, outcome: string, records: number): void {
    if (records > 0) {
        internalLogsProducerRecordsCounter.inc({ source, outcome }, records)
    }
}

/**
 * Delivery runs in the background, so a slow or down capture-logs never slows the caller. A record is lost only when
 * it is invalid, the buffer is full, its retries time out, capture-logs rejects it, or `drain` times out.
 */
export class InternalLogsProducer {
    private readonly enabled: boolean
    private readonly isTeamEnabled: ValueMatcher<number>
    // One batch per source and team, so records that wait for a free request slot leave together in large requests.
    private waiting = new Map<string, Batch>()
    // Counts waiting and in-flight records, because each one holds its bytes until its request settles.
    private bufferedBytes = 0
    private inFlight = new Set<Request>()
    // Set when `drain` ends. After it, nothing is sent or counted twice, and a retrying request stops.
    private stopped = false

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
        let invalid = 0
        let dropped = 0
        let abandoned = 0
        for (const entry of entries) {
            if (!this.isTeamEnabled(entry.team_id)) {
                continue
            }
            if (this.stopped) {
                abandoned++
                continue
            }
            let record: string
            try {
                record = JSON.stringify(toOtlpLogRecord(entry))
            } catch {
                invalid++
                continue
            }
            const bytes = Buffer.byteLength(record)
            if (this.bufferedBytes + bytes > this.config.LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES) {
                dropped++
                continue
            }
            this.bufferedBytes += bytes
            const key = `${source}:${entry.team_id}`
            const batch = this.waiting.get(key) ?? { source, teamId: entry.team_id, records: [] }
            batch.records.push(record)
            this.waiting.set(key, batch)
        }
        countRecords(source, 'invalid', invalid)
        countRecords(source, 'dropped', dropped)
        countRecords(source, 'abandoned', abandoned)
        this.report()
    }

    /** Starts sending the waiting records. Never throws. */
    flush(): void {
        this.pump()
    }

    /** Sends what is left until the timeout, then stops and counts the rest as abandoned. Call on shutdown. */
    async drain(timeoutMs: number): Promise<void> {
        const deadline = Date.now() + timeoutMs
        this.pump()
        while (!this.stopped && !this.isIdle() && Date.now() < deadline) {
            await delay(Math.min(DRAIN_POLL_MS, deadline - Date.now()))
        }
        if (!this.stopped && !this.isIdle()) {
            this.abandon()
        }
        this.stopped = true
    }

    private abandon(): void {
        this.stopped = true
        const unsent = [...this.waiting.values(), ...this.inFlight]
        for (const { source, records } of unsent) {
            countRecords(source, 'abandoned', records.length)
        }
        logger.warn('Internal logs producer stopped before all records were sent', {
            abandonedRecords: unsent.reduce((sum, { records }) => sum + records.length, 0),
            inFlightRequests: this.inFlight.size,
        })
        this.waiting.clear()
        this.bufferedBytes = [...this.inFlight].reduce((sum, request) => sum + request.bytes, 0)
        this.report()
    }

    private pump(): void {
        while (this.inFlight.size < this.config.LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT && this.waiting.size > 0) {
            const [key, batch] = this.waiting.entries().next().value!
            // Moves the rest of the batch to the back, so each team gets its turn.
            this.waiting.delete(key)
            const request = takeRequest(batch)
            if (batch.records.length > 0) {
                this.waiting.set(key, batch)
            }
            this.inFlight.add(request)
            void this.deliver(request).finally(() => {
                this.inFlight.delete(request)
                this.bufferedBytes -= request.bytes
                this.pump()
            })
        }
        this.report()
    }

    private isIdle(): boolean {
        return this.inFlight.size === 0 && this.waiting.size === 0
    }

    private report(): void {
        internalLogsProducerBufferedBytesGauge.set(this.bufferedBytes)
        internalLogsProducerInFlightGauge.set(this.inFlight.size)
    }

    private async deliver({ source, teamId, records }: Batch): Promise<void> {
        const body = toOtlpBody(source, records)
        const deadline = Date.now() + this.config.LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS
        for (let attempt = 0; !this.stopped; attempt++) {
            const result = await this.attempt(source, teamId, body, deadline)
            if (this.stopped) {
                return
            }
            if (result.outcome !== 'retry') {
                countRecords(source, result.outcome, records.length)
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
                countRecords(source, 'failed', records.length)
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
    }

    private async attempt(source: string, teamId: number, body: string, deadline: number): Promise<AttemptResult> {
        let timer: NodeJS.Timeout | undefined
        try {
            // A team lookup has no timeout of its own, so a stalled Postgres would hold this request slot past the deadline.
            const team = await Promise.race([
                this.teamManager.getTeam(teamId),
                new Promise<never>((_, reject) => {
                    timer = setTimeout(() => reject(new Error('team lookup timed out')), deadline - Date.now())
                }),
            ])
            if (this.stopped) {
                return { outcome: 'retry', detail: 'stopped' }
            }
            if (!team) {
                return { outcome: 'unknown_team', detail: String(teamId) }
            }
            const response = await internalFetch(this.config.LOGS_INTERNAL_PRODUCER_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${team.api_token}`,
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
        } finally {
            clearTimeout(timer)
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

/** Removes up to MAX_REQUEST_RECORD_BYTES of records from the front of the batch, and at least one. */
function takeRequest(batch: Batch): Request {
    let count = 0
    let bytes = 0
    while (count < batch.records.length) {
        const recordBytes = Buffer.byteLength(batch.records[count])
        if (count > 0 && bytes + recordBytes > MAX_REQUEST_RECORD_BYTES) {
            break
        }
        bytes += recordBytes
        count++
    }
    return { source: batch.source, teamId: batch.teamId, records: batch.records.splice(0, count), bytes }
}

function toOtlpBody(source: string, records: string[]): string {
    const resource = JSON.stringify({
        attributes: [{ key: 'service.name', value: { stringValue: SERVICE_NAMES[source] } }],
    })
    return `{"resourceLogs":[{"resource":${resource},"scopeLogs":[{"scope":${JSON.stringify({ name: source })},"logRecords":[${records.join(',')}]}]}]}`
}
