import { MessageKey } from '../../kafka/producer'

/** A Kafka message with a Buffer value, used by IngestionOutputs. */
export type IngestionOutputMessage = {
    value: Buffer | null
    key?: MessageKey
    headers?: Record<string, string>
    /**
     * Optional team ID for team-based producer routing.
     *
     * When set, `TeamRoutedIngestionOutput` uses this to decide which producer
     * handles the message (e.g. WarpStream for specific teams, default for the rest).
     * Ignored by producers — not sent as a Kafka header or included in the message payload.
     */
    teamId?: number
}
