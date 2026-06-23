import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { logger } from '../../../utils/logger'
import { SessionBlockMetadata } from './session-block-metadata'

// per-session index, JSONL sidecar
export class S3ManifestStore {
    constructor(
        private readonly s3Client: S3Client,
        private readonly bucket: string,
        private readonly prefix: string
    ) {}

    public async writeManifest(blocks: SessionBlockMetadata[]): Promise<void> {
        // skip blocks without a URL
        const rows = blocks.filter((block) => block.blockUrl !== null)
        if (rows.length === 0) {
            return
        }

        const body = rows.map((block) => JSON.stringify(toManifestRow(block))).join('\n') + '\n'
        const key = `${this.prefix}/manifests/${rows[0].batchId}.jsonl`

        await this.s3Client.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: key,
                Body: body,
                ContentType: 'application/x-ndjson',
            })
        )

        logger.info('🗂️', 's3_manifest_store_wrote', { key, sessions: rows.length })
    }
}

interface ManifestRow {
    session_id: string
    team_id: number
    distinct_id: string
    batch_id: string
    block_url: string
    block_length: number
    start_timestamp: string
    end_timestamp: string
    event_count: number
    message_count: number
    first_url: string | null
}

function toManifestRow(block: SessionBlockMetadata): ManifestRow {
    return {
        session_id: block.sessionId,
        team_id: block.teamId,
        distinct_id: block.distinctId,
        batch_id: block.batchId,
        block_url: block.blockUrl as string,
        block_length: block.blockLength,
        start_timestamp: block.startDateTime.toISO() ?? '',
        end_timestamp: block.endDateTime.toISO() ?? '',
        event_count: block.eventCount,
        message_count: block.messageCount,
        first_url: block.firstUrl,
    }
}
