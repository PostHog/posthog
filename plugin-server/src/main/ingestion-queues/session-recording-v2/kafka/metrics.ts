import { eventDroppedCounter } from '../../metrics'

export class KafkaMetrics {
    private static instance: KafkaMetrics

    public constructor() {}

    public static getInstance(): KafkaMetrics {
        if (!KafkaMetrics.instance) {
            KafkaMetrics.instance = new KafkaMetrics()
        }
        return KafkaMetrics.instance
    }

    public incrementMessageDropped(event_type: string, drop_cause: string): void {
        eventDroppedCounter.labels({ event_type, drop_cause }).inc()
    }
}
