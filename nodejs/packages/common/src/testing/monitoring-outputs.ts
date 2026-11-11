import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '~/config/kafka-topics'
import { KafkaProducerWrapper } from '~/kafka/producer'
import { APP_METRICS_OUTPUT, LOG_ENTRIES_OUTPUT } from '~/outputs/index'
import { IngestionOutputs } from '~/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/outputs/single-ingestion-output'

export function createTestMonitoringOutputs(kafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [APP_METRICS_OUTPUT]: new SingleIngestionOutput(APP_METRICS_OUTPUT, KAFKA_APP_METRICS_2, kafkaProducer, 'test'),
        [LOG_ENTRIES_OUTPUT]: new SingleIngestionOutput(LOG_ENTRIES_OUTPUT, KAFKA_LOG_ENTRIES, kafkaProducer, 'test'),
    })
}
