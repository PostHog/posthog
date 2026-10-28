import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { sanitizeForUTF8 } from '~/common/utils/strings'
import type { TeamManager } from '~/common/utils/team-manager'
import type { ValueMatcher } from '~/types'

import type { LogsIngestionConsumerConfig } from './config'
import { INTERNAL_LOGS_HTTP_HEADER, INTERNAL_SOURCE_POLICIES, signInternalLogs } from './internal-logs'

// A source needs a name here as well as a policy, because the name is what a team filters on in the logs product.
const SERVICE_NAMES: Readonly<Record<string, string>> = {
    hog_flow: 'posthog-internal-workflows',
}

// OTLP SeverityNumber for the first value of each range.
const SEVERITY_NUMBERS: Readonly<Record<string, number>> = { debug: 5, info: 9, warn: 13, error: 17 }

// Half of capture-logs' default 2 MiB body limit, which leaves room for the envelope.
const MAX_REQUEST_RECORD_BYTES = 1024 * 1024

// A JSON-escaped character takes at most 6 bytes, so a message cut to this length always fits in one request.
const MAX_MESSAGE_LENGTH = 128 * 1024

/** One row of `log_entries`, the table every internal log source writes to. */
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
>

type QueuedBatch = { source: string; teamId: number; records: OtlpLogRecord[] }

const internalLogsProducerBatchesCounter = new Counter({
    name: 'logs_internal_producer_batches_total',
    help: 'Signed internal logs batches sent to capture-logs, by source and outcome. Only a sent batch reaches the logs product.',
    labelNames: ['source', 'outcome'],
})

/** Sends a copy of PostHog's own logs to the logs product, signed so the logs consumer does not bill them. */
export class InternalLogsProducer {
    private readonly enabled: boolean
    private readonly isTeamEnabled: ValueMatcher<number>
    private queued = new Map<string, QueuedBatch>()
    private inFlight = 0

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

    /** Never throws. A caller must not await the result on a hot path, because capture-logs can be slow. */
    async flush(): Promise<void> {
        const batches = [...this.queued.values()]
        this.queued = new Map()
        await Promise.all(
            batches.flatMap(({ source, teamId, records }) =>
                splitBySize(records).map((chunk) => this.sendBatch(source, teamId, chunk))
            )
        )
    }

    private async sendBatch(source: string, teamId: number, records: OtlpLogRecord[]): Promise<void> {
        if (this.inFlight >= this.config.LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT) {
            internalLogsProducerBatchesCounter.inc({ source, outcome: 'dropped' })
            return
        }
        this.inFlight++
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                internalLogsProducerBatchesCounter.inc({ source, outcome: 'unknown_team' })
                return
            }
            const response = await internalFetch(this.config.LOGS_INTERNAL_PRODUCER_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${team.api_token}`,
                    // Signed after the team lookup, so a slow lookup cannot age the signature.
                    [INTERNAL_LOGS_HTTP_HEADER]: signInternalLogs(
                        this.config.LOGS_INTERNAL_INGESTION_SIGNING_KEYS,
                        source,
                        teamId
                    ),
                },
                body: JSON.stringify(toOtlpJson(source, records)),
            })
            await response.dump()
            const ok = response.status >= 200 && response.status < 300
            internalLogsProducerBatchesCounter.inc({ source, outcome: ok ? 'sent' : 'rejected' })
            if (!ok) {
                logger.warn('Internal logs batch rejected by capture-logs', { source, teamId, status: response.status })
            }
        } catch (error) {
            internalLogsProducerBatchesCounter.inc({ source, outcome: 'failed' })
            logger.warn('Internal logs batch failed', { source, teamId, error: String(error) })
        } finally {
            this.inFlight--
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

function splitBySize(records: OtlpLogRecord[]): OtlpLogRecord[][] {
    const chunks: OtlpLogRecord[][] = []
    let chunk: OtlpLogRecord[] = []
    let chunkBytes = 0
    for (const record of records) {
        const bytes = Buffer.byteLength(JSON.stringify(record))
        if (chunk.length > 0 && chunkBytes + bytes > MAX_REQUEST_RECORD_BYTES) {
            chunks.push(chunk)
            chunk = []
            chunkBytes = 0
        }
        chunk.push(record)
        chunkBytes += bytes
    }
    if (chunk.length > 0) {
        chunks.push(chunk)
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
