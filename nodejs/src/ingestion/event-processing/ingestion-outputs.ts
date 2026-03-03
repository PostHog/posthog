import { KafkaProducerWrapper } from '../../kafka/producer'

export const EVENTS_OUTPUT = 'events' as const
export type EventOutput = typeof EVENTS_OUTPUT

export interface IngestionOutputConfig {
    topic: string
    producer: KafkaProducerWrapper
}

export class IngestionOutputs<O extends string> {
    constructor(private outputs: Record<O, IngestionOutputConfig>) {}

    resolve(output: O): IngestionOutputConfig {
        return this.outputs[output]
    }
}
