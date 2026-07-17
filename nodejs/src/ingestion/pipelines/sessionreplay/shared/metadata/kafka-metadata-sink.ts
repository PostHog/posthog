import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

import { SessionBlockMetadata } from './session-block-metadata'

/** Sink for per-block session metadata at flush time (ClickHouse for the primary, the ML topic for the mirror). */
export interface SessionMetadataSink {
    storeSessionBlocks(blocks: SessionBlockMetadata[]): Promise<void>
}

/** A keyed record to be JSON-serialized onto a Kafka output. */
export interface MetadataRecord {
    key: string
    value: unknown
}

/**
 * Base sink that maps a flush's blocks to keyed records and produces them as JSON to one Kafka output.
 * Subclasses supply the output and the per-block mapping; the produce mechanism is shared.
 */
export abstract class KafkaMetadataSink<O extends string> implements SessionMetadataSink {
    constructor(
        protected readonly outputs: IngestionOutputs<O>,
        private readonly output: O
    ) {}

    protected abstract toRecords(blocks: SessionBlockMetadata[]): MetadataRecord[]

    public async storeSessionBlocks(blocks: SessionBlockMetadata[]): Promise<void> {
        const records = this.toRecords(blocks)
        // queueMessages awaits delivery acks, so offsets commit only once the metadata is durably on Kafka.
        await this.outputs.queueMessages(
            this.output,
            records.map((record) => ({ key: record.key, value: Buffer.from(JSON.stringify(record.value)) }))
        )
    }
}
