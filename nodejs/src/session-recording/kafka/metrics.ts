import { eventDroppedCounter } from '~/common/metrics'

export class KafkaMetrics {
    public static incrementMessageDropped(event_type: string, drop_cause: string): void {
        eventDroppedCounter.labels({ event_type, drop_cause }).inc()
    }
}
