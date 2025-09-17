import { eventDroppedCounter } from '../../metrics'

export class KafkaMetrics {
    public static incrementMessageDropped(event_type: string, drop_cause: string): void {
        eventDroppedCounter.labels({ event_type, drop_cause }).inc()
    }
}
