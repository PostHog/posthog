import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { sanitizeForUTF8 } from '~/common/utils/strings'
import type { TeamManager } from '~/common/utils/team-manager'
import type { ValueMatcher } from '~/types'

import type { LogsIngestionConsumerConfig } from './config'
import { INTERNAL_SOURCE_POLICIES, signInternalLogs } from './internal-logs'

const INTERNAL_LOGS_HTTP_HEADER = 'x-posthog-internal'

const SERVICE_NAMES: Readonly<Record<string, string>> = {
    hog_flow: 'posthog-workflows',
}

// OTLP SeverityNumber for the first value of each range.
const SEVERITY_NUMBERS: Readonly<Record<string, number>> = { debug: 5, info: 9, warn: 13, error: 17 }

// Half of capture-logs' default 2 MiB body limit, which leaves room for the envelope.
const MAX_REQUEST_RECORD_BYTES = 1024 * 1024

export type InternalLogRecord = {
    source: string
    teamId: number
    timestamp: DateTime
    level: string
    message: string
    attributes: Record<string, string>
}

export type InternalLogsProducerConfig = Pick<
    LogsIngestionConsumerConfig,
    | 'LOGS_INTERNAL_INGESTION_SIGNING_KEYS'
    | 'LOGS_INTERNAL_PRODUCER_URL'
    | 'LOGS_INTERNAL_PRODUCER_TEAMS'
    | 'LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT'
>

const internalLogsProducerBatchesCounter = new Counter({
    name: 'logs_internal_producer_batches_total',
    help: 'Signed internal logs batches sent to capture-logs, by source and outcome. Only a sent batch reaches the logs product.',
    labelNames: ['source', 'outcome'],
})

/** Sends a copy of PostHog's own logs to the logs product, signed so the logs consumer does not bill them. */
export class InternalLogsProducer {
    private readonly enabled: boolean
    private readonly isTeamEnabled: ValueMatcher<number>
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

    accepts(source: string, teamId: number): boolean {
        return this.enabled && Object.hasOwn(INTERNAL_SOURCE_POLICIES, source) && this.isTeamEnabled(teamId)
    }

    /** Never throws. A caller must not await the result on a hot path, because capture-logs can be slow. */
    async send(records: InternalLogRecord[]): Promise<void> {
        const batches = new Map<string, { source: string; teamId: number; records: OtlpLogRecord[] }>()
        for (const record of records) {
            if (!this.accepts(record.source, record.teamId)) {
                continue
            }
            const key = `${record.source}:${record.teamId}`
            const batch = batches.get(key) ?? { source: record.source, teamId: record.teamId, records: [] }
            batch.records.push(toOtlpLogRecord(record))
            batches.set(key, batch)
        }
        await Promise.all(
            [...batches.values()].flatMap(({ source, teamId, records }) =>
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
                    // Signed here, after the team lookup, so the signature is fresh when the request leaves.
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

function toOtlpLogRecord(record: InternalLogRecord): OtlpLogRecord {
    return {
        timeUnixNano: (BigInt(record.timestamp.toMillis()) * 1_000_000n).toString(),
        severityText: record.level.toUpperCase(),
        severityNumber: SEVERITY_NUMBERS[record.level] ?? 0,
        // capture-logs rejects a whole request that holds one unpaired surrogate.
        body: { stringValue: sanitizeForUTF8(record.message) },
        attributes: Object.entries(record.attributes).map(([key, value]) => ({ key, value: { stringValue: value } })),
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
                    attributes: [
                        { key: 'service.name', value: { stringValue: SERVICE_NAMES[source] ?? `posthog-${source}` } },
                    ],
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
