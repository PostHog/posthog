import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { Counter } from 'prom-client'

import { MESSAGE_ASSETS_OUTPUT, MessageAssetsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

import { CyclotronInvocationQueueParametersEmailType } from '../../../schema/cyclotron'
import { safeClickhouseString } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { CyclotronJobInvocationHogFunction } from '../../types'
import { resolveEmailEngagementDistinctId } from './email-tracking.service'

const counterMessageAssetsCaptured = new Counter({
    name: 'cdp_message_assets_captured',
    help: 'Sent-email assets snapshotted to object storage and recorded in ClickHouse.',
    labelNames: ['kind'],
})

const counterMessageAssetsFailed = new Counter({
    name: 'cdp_message_assets_failed',
    help: 'Asset captures that failed (object-storage write or Kafka produce). Best-effort — never disrupts the send.',
    labelNames: ['stage'],
})

export interface MessageAssetsServiceConfig {
    MESSAGE_ASSETS_CAPTURE_ENABLED: boolean
    MESSAGE_ASSETS_OBJECT_STORAGE_ENDPOINT: string
    MESSAGE_ASSETS_OBJECT_STORAGE_REGION: string
    MESSAGE_ASSETS_OBJECT_STORAGE_BUCKET: string
    MESSAGE_ASSETS_OBJECT_STORAGE_ACCESS_KEY_ID: string
    MESSAGE_ASSETS_OBJECT_STORAGE_SECRET_ACCESS_KEY: string
    MESSAGE_ASSETS_OBJECT_STORAGE_FOLDER: string
}

/**
 * Metadata row written to the `message_assets` ClickHouse table via Kafka. The
 * rendered HTML body itself lives in object storage at `s3_key` — this row holds
 * only what the workflow "Assets" tab needs to list and locate the asset.
 */
export interface MessageAssetRow {
    team_id: number
    function_kind: 'hog_flow' | 'hog_function'
    function_id: string
    parent_run_id: string
    invocation_id: string
    action_id: string
    kind: 'email'
    distinct_id: string
    person_id: string
    recipient: string
    subject: string
    s3_key: string
    status: 'sent'
    sent_at: string // ISO microsecond DateTime64
    version: string // microsecond-precision UInt64, serialized as string to dodge JS's 53-bit cap
    is_deleted: 0 | 1
}

const microsecondsSinceEpoch = (): string => {
    const ms = BigInt(Date.now())
    const subMs = BigInt(Math.floor((performance.now() % 1) * 1000))
    return (ms * 1000n + subMs).toString()
}

const isoMicroseconds = (date: Date): string => {
    // ClickHouse DateTime64(6) accepts 'YYYY-MM-DD HH:MM:SS.ffffff'.
    return date.toISOString().replace('T', ' ').replace('Z', '000')
}

/**
 * Captures a snapshot of every successfully sent workflow email: the rendered
 * HTML is written to object storage and a compact metadata row is produced to
 * the `message_assets` ClickHouse table.
 *
 * Capture is strictly best-effort — `captureSentEmail` never throws, so a
 * storage or Kafka hiccup can never fail an email that already went out. Gated
 * by the global `MESSAGE_ASSETS_CAPTURE_ENABLED` kill-switch.
 */
export class MessageAssetsService {
    private s3Client: S3Client | null

    constructor(
        private outputs: IngestionOutputs<MessageAssetsOutput>,
        private config: MessageAssetsServiceConfig
    ) {
        this.s3Client = this.config.MESSAGE_ASSETS_OBJECT_STORAGE_ENDPOINT
            ? new S3Client({
                  region: this.config.MESSAGE_ASSETS_OBJECT_STORAGE_REGION,
                  endpoint: this.config.MESSAGE_ASSETS_OBJECT_STORAGE_ENDPOINT,
                  forcePathStyle: true,
                  credentials: this.config.MESSAGE_ASSETS_OBJECT_STORAGE_ACCESS_KEY_ID
                      ? {
                            accessKeyId: this.config.MESSAGE_ASSETS_OBJECT_STORAGE_ACCESS_KEY_ID,
                            secretAccessKey: this.config.MESSAGE_ASSETS_OBJECT_STORAGE_SECRET_ACCESS_KEY,
                        }
                      : undefined,
              })
            : null
    }

    // `message_assets/team-{teamId}/{functionId}/{invocationId}/{actionId}.html`.
    // The Django assets API derives the same key from the row's metadata to serve
    // the content, so the shape must stay in lockstep with `assets_storage.py`.
    private objectKey(row: MessageAssetRow): string {
        const action = row.action_id || 'default'
        return `${this.config.MESSAGE_ASSETS_OBJECT_STORAGE_FOLDER}/team-${row.team_id}/${row.function_id}/${row.invocation_id}/${action}.html`
    }

    async captureSentEmail(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<void> {
        if (!this.config.MESSAGE_ASSETS_CAPTURE_ENABLED) {
            return
        }
        if (!params.html) {
            // Text-only email — nothing to snapshot. Metrics still record the send.
            return
        }
        // Only emails sent as a workflow step are retrievable: the Assets API queries
        // function_kind='hog_flow' keyed by the action node id. A standalone email-
        // destination send has no action id, so capturing it would write a ClickHouse
        // row + S3 object that nothing can ever surface — skip it.
        if (!invocation.state.actionId) {
            return
        }

        const row = this.buildRow(invocation, params)

        if (!this.s3Client) {
            counterMessageAssetsFailed.inc({ stage: 'storage' })
            return
        }

        try {
            await this.s3Client.send(
                new PutObjectCommand({
                    Bucket: this.config.MESSAGE_ASSETS_OBJECT_STORAGE_BUCKET,
                    Key: row.s3_key,
                    Body: params.html,
                    ContentType: 'text/html; charset=utf-8',
                })
            )
        } catch (error) {
            // Nothing stored — don't produce a row that would point at a missing object.
            counterMessageAssetsFailed.inc({ stage: 'storage' })
            logger.error('⚠️', `failed to write message asset to object storage: ${error}`, {
                error: String(error),
                invocation_id: invocation.id,
            })
            captureException(error)
            return
        }

        try {
            await this.outputs.produce(MESSAGE_ASSETS_OUTPUT, {
                // Partition by invocation_id so retried produces for the same
                // asset land on the same partition and collapse cleanly via the
                // ReplacingMergeTree.
                key: Buffer.from(row.invocation_id),
                value: Buffer.from(safeClickhouseString(JSON.stringify(row))),
            })
        } catch (error) {
            // The HTML is in object storage but the metadata row didn't land — the
            // object is orphaned (unservable) until the lifecycle policy purges it.
            // Distinct 'kafka' stage so operators can tell this apart from a storage miss.
            counterMessageAssetsFailed.inc({ stage: 'kafka' })
            logger.error('⚠️', `failed to produce message asset row: ${error}`, {
                error: String(error),
                invocation_id: invocation.id,
            })
            captureException(error)
            return
        }

        counterMessageAssetsCaptured.inc({ kind: row.kind })
    }

    private buildRow(
        invocation: CyclotronJobInvocationHogFunction,
        params: CyclotronInvocationQueueParametersEmailType
    ): MessageAssetRow {
        const row: MessageAssetRow = {
            team_id: invocation.teamId,
            // captureSentEmail only reaches buildRow for in-workflow email steps (an
            // action id is present), so these always attribute to the workflow.
            function_kind: 'hog_flow',
            function_id: invocation.functionId,
            parent_run_id: invocation.parentRunId ?? '',
            invocation_id: invocation.id,
            action_id: invocation.state.actionId ?? '',
            kind: 'email',
            distinct_id: resolveEmailEngagementDistinctId(invocation) ?? '',
            person_id: invocation.state.globals.person?.id ?? '',
            recipient: params.to.email,
            subject: params.subject,
            s3_key: '',
            status: 'sent',
            sent_at: isoMicroseconds(new Date()),
            version: microsecondsSinceEpoch(),
            is_deleted: 0,
        }
        row.s3_key = this.objectKey(row)
        return row
    }
}
