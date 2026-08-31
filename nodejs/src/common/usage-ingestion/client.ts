import { create } from '@bufbuild/protobuf'
import { Client, Code, ConnectError, createClient } from '@connectrpc/connect'
import { createGrpcTransport } from '@connectrpc/connect-node'
import { Counter } from 'prom-client'

import {
    BillingUsageRecordSchema,
    IngestBillingUsageRequestSchema,
    UsageIngestion,
} from '~/common/generated/usage-ingestion/usage_ingestion/v1/service_pb'
import { logger } from '~/common/utils/logger'

const usageRecordsSentCounter = new Counter({
    name: 'usage_ingestion_records_sent_total',
    help: 'Usage records accepted by the usage-ingestion service.',
    labelNames: ['producer_id', 'usage_key'],
})

const usageRecordsFailedCounter = new Counter({
    name: 'usage_ingestion_records_failed_total',
    help: 'Usage records dropped after the client exhausted its retries.',
    labelNames: ['producer_id', 'usage_key', 'error_code'],
})

const RETRYABLE_CODES = new Set([Code.Unavailable, Code.DeadlineExceeded, Code.ResourceExhausted, Code.Aborted])

export interface UsageRecordInput {
    /** Unique per (teamId, producerId, usageKey). Reused verbatim on retry, which is what makes ingest idempotent. */
    recordId: string
    teamId: number
    usageKey: string
    unit: string
    quantity: number
    timestampMs: number
}

export interface UsageIngestionClientConfig {
    addr: string
    producerId: string
    timeoutMs?: number
    maxBatchSize?: number
    useTls?: boolean
}

export class UsageIngestionClient {
    private readonly client: Client<typeof UsageIngestion>
    private readonly producerId: string
    private readonly maxBatchSize: number

    constructor(config: UsageIngestionClientConfig) {
        const scheme = config.useTls ? 'https' : 'http'
        this.client = createClient(
            UsageIngestion,
            createGrpcTransport({
                baseUrl: `${scheme}://${config.addr}`,
                defaultTimeoutMs: config.timeoutMs ?? 5_000,
            })
        )
        this.producerId = config.producerId
        this.maxBatchSize = config.maxBatchSize ?? 500
    }

    async ingest(records: UsageRecordInput[]): Promise<void> {
        if (records.length === 0) {
            return
        }
        const chunks: UsageRecordInput[][] = []
        for (let i = 0; i < records.length; i += this.maxBatchSize) {
            chunks.push(records.slice(i, i + this.maxBatchSize))
        }
        await Promise.all(chunks.map((chunk) => this.ingestChunk(chunk)))
    }

    private async ingestChunk(chunk: UsageRecordInput[], attempt = 0): Promise<void> {
        const request = create(IngestBillingUsageRequestSchema, {
            records: chunk.map((record) =>
                create(BillingUsageRecordSchema, {
                    recordId: record.recordId,
                    producerId: this.producerId,
                    teamId: BigInt(record.teamId),
                    usageKey: record.usageKey,
                    unit: record.unit,
                    quantity: BigInt(record.quantity),
                    timestampMs: BigInt(record.timestampMs),
                })
            ),
        })

        try {
            await this.client.ingestBillingUsage(request)
            for (const record of chunk) {
                usageRecordsSentCounter.inc({ producer_id: this.producerId, usage_key: record.usageKey })
            }
        } catch (error) {
            const code = error instanceof ConnectError ? error.code : Code.Unknown
            if (attempt === 0 && RETRYABLE_CODES.has(code)) {
                await this.ingestChunk(chunk, attempt + 1)
                return
            }
            for (const record of chunk) {
                usageRecordsFailedCounter.inc({
                    producer_id: this.producerId,
                    usage_key: record.usageKey,
                    error_code: Code[code] ?? 'unknown',
                })
            }
            logger.warn('⚠️', 'failed to ingest usage records', {
                producerId: this.producerId,
                records: chunk.length,
                error: String(error),
            })
        }
    }
}
