/** Produces anonymized, pseudonymized block metadata to the ML Kafka topic for the Parquet sink to consume. */
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import {
    KafkaMetadataSink,
    MetadataRecord,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/kafka-metadata-sink'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { ML_BLOCK_METADATA_OUTPUT, MlBlockMetadataOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { toBlockMetadataRow } from './block-metadata-row'

export class MlBlockMetadataSink extends KafkaMetadataSink<MlBlockMetadataOutput> {
    constructor(
        outputs: IngestionOutputs<MlBlockMetadataOutput>,
        private readonly pseudonymSecret: string | Buffer
    ) {
        super(outputs, ML_BLOCK_METADATA_OUTPUT)
    }

    protected toRecords(blocks: SessionBlockMetadata[]): MetadataRecord[] {
        const records: MetadataRecord[] = []
        for (const block of blocks) {
            const row = toBlockMetadataRow(block, this.pseudonymSecret)
            if (row) {
                // Keyed by the pseudonymous session id so a recording's blocks land on one partition.
                records.push({ key: row.session_id, value: row })
            }
        }
        return records
    }
}
