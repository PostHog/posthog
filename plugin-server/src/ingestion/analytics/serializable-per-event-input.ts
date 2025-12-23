/**
 * Serializable wrapper for PerEventProcessingInput to cross worker thread boundary.
 *
 * Note: groupStoreForBatch is NOT serialized - each worker has its own GroupStore.
 * The Kafka Message is also not serialized - it's only needed for context in the main thread.
 */
import { EventHeaders, PipelineEvent, Team } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { Serializable } from '../pipelines/multithreaded/serializable'
import { PerEventProcessingInput } from './per-event-processing-subpipeline'

/**
 * The subset of PerEventProcessingInput that can be serialized.
 * Workers receive this and add their own groupStoreForBatch.
 */
export interface SerializedPerEventInput {
    event: PipelineEvent
    team: Team
    headers: EventHeaders
    groupKey: string
}

/**
 * Serializable wrapper for per-event processing input.
 */
export class SerializablePerEventInput implements Serializable {
    private data: SerializedPerEventInput

    constructor(input: PerEventProcessingInput) {
        this.data = {
            event: input.event,
            team: input.team,
            headers: input.headers,
            groupKey: `${input.event.token ?? ''}:${input.event.distinct_id ?? ''}`,
        }
    }

    serialize(): Uint8Array {
        return new TextEncoder().encode(JSON.stringify(this.data))
    }

    static deserialize(data: Uint8Array): SerializedPerEventInput {
        return parseJSON(new TextDecoder().decode(data)) as SerializedPerEventInput
    }
}
