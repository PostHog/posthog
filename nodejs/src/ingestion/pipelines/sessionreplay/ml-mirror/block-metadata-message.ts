/** Parses block-metadata Kafka messages (JSON rows produced by MlBlockMetadataSink) back into rows. */
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { isWellFormedRow } from './block-metadata-columns'
import { MlBlockMetadataRow } from './block-metadata-row'

export function parseBlockMetadataMessages(messages: readonly { value: Buffer | null }[]): MlBlockMetadataRow[] {
    const rows: MlBlockMetadataRow[] = []
    for (const message of messages) {
        if (!message.value) {
            continue
        }
        let row: unknown
        try {
            row = parseJSON(message.value.toString('utf8'))
        } catch (error) {
            // Skip malformed rows rather than wedge the partition; they're rare and non-fatal for training data.
            logger.warn('🪶', 'ml_parquet_metadata_parse_failed', { error: String(error) })
            continue
        }
        if (!isWellFormedRow(row)) {
            logger.warn('🪶', 'ml_parquet_metadata_row_invalid')
            continue
        }
        rows.push(row)
    }
    return rows
}
