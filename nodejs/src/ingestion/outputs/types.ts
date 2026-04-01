import { MessageKey } from '../../kafka/producer'

/** A Kafka message with a Buffer value, used by IngestionOutputs. */
export type IngestionOutputMessage = {
    value: Buffer | null
    key?: MessageKey
    headers?: Record<string, string>
}
