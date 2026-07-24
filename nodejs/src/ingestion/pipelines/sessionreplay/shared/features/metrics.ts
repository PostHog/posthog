import { Counter } from 'prom-client'

export class SessionFeatureStoreMetrics {
    private static readonly oversizedMessagesDropped = new Counter({
        name: 'session_feature_store_oversized_messages_dropped_total',
        help: 'Count of session feature messages dropped because their serialized size exceeded the configured limit.',
    })

    public static incrementOversizedMessagesDropped(): void {
        this.oversizedMessagesDropped.inc()
    }
}
