import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SessionMetadataSink } from '~/ingestion/pipelines/sessionreplay/shared/metadata/kafka-metadata-sink'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { ML_BLOCK_METADATA_OUTPUT, MlBlockMetadataOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { toBlockMetadataRow } from './block-metadata-row'
import { MlKeyReader } from './privacy/reader'
import { sessionKeyId, tableKeyString } from './privacy/schema'
import { encryptedKafkaValue } from './privacy/transport'
import { usesRawSessionIdentifiers } from './session-identifier-format'

export class MlBlockMetadataSink implements SessionMetadataSink {
    constructor(
        private readonly outputs: IngestionOutputs<MlBlockMetadataOutput>,
        private readonly pseudonymSecret: string | Buffer,
        private readonly privacy?: MlKeyReader
    ) {}

    public async storeSessionBlocks(blocks: SessionBlockMetadata[]): Promise<void> {
        const currentBlocks = blocks.filter(
            (block) => block.blockUrl && !block.isDeleted && usesRawSessionIdentifiers(block.sessionId)
        )
        if (currentBlocks.length && !this.privacy) {
            throw new Error('ML v2 metadata requires privacy configuration')
        }
        const keys =
            (await this.privacy?.read(currentBlocks.map((block) => sessionKeyId(block.teamId, block.sessionId)))) ??
            new Map()
        const messages = blocks.flatMap((block) => {
            const row = toBlockMetadataRow(block, this.pseudonymSecret)
            const key = keys.get(tableKeyString(sessionKeyId(block.teamId, block.sessionId)))
            if (!row || (usesRawSessionIdentifiers(block.sessionId) && !key)) {
                return []
            }
            return [{ key: row.session_id, ...encryptedKafkaValue(key, 'metadata', Buffer.from(JSON.stringify(row))) }]
        })
        await this.outputs.queueMessages(ML_BLOCK_METADATA_OUTPUT, messages)
    }
}
