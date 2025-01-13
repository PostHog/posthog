import { Counter } from 'prom-client'

export class KafkaMetrics {
    private static instance: KafkaMetrics
    private readonly messageReceived: Counter<string>
    private readonly libVersionWarning: Counter<string>

    private constructor() {
        this.messageReceived = new Counter({
            name: 'recording_blob_ingestion_v2_kafka_message_received',
            help: 'The number of messages we have received from Kafka',
            labelNames: ['partition'],
        })

        this.libVersionWarning = new Counter({
            name: 'recording_blob_ingestion_v2_lib_version_warning_counter',
            help: 'the number of times we have seen a message with a lib version that is too old, each _might_ cause an ingestion warning if not debounced',
        })
    }

    public static getInstance(): KafkaMetrics {
        if (!KafkaMetrics.instance) {
            KafkaMetrics.instance = new KafkaMetrics()
        }
        return KafkaMetrics.instance
    }

    public incrementMessageReceived(partition: number): void {
        this.messageReceived.inc({ partition })
    }

    public incrementLibVersionWarning(): void {
        this.libVersionWarning.inc()
    }
}
