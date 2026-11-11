use std::time::Duration;

use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use tokio::time::sleep;
use tracing::{error, info, warn};

/// Handles Kafka consumer errors: retries with backoff for retriable errors,
/// returns Some(e) for fatal/canceled errors so the caller can stop.
/// `metric_name` is the counter used for error metrics (e.g. BATCH_CONSUMER_KAFKA_ERROR).
pub(crate) async fn handle_kafka_error(
    e: KafkaError,
    current_count: u64,
    metric_name: &'static str,
) -> Option<KafkaError> {
    match &e {
        KafkaError::MessageConsumption(code) => {
            match code {
                RDKafkaErrorCode::PartitionEOF => {
                    metrics::counter!(
                        metric_name,
                        &[("level", "info"), ("error", "partition_eof"),]
                    )
                    .increment(1);
                }
                RDKafkaErrorCode::OperationTimedOut => {
                    metrics::counter!(
                        metric_name,
                        &[("level", "info"), ("error", "op_timed_out"),]
                    )
                    .increment(1);
                }
                RDKafkaErrorCode::OffsetOutOfRange => {
                    warn!("Offset out of range - seeking to configured offset reset policy",);
                    metrics::counter!(
                        metric_name,
                        &[("level", "info"), ("error", "offset_out_of_range"),]
                    )
                    .increment(1);
                    sleep(Duration::from_millis(500)).await;
                }
                _ => {
                    warn!("Kafka consumer error: {code:?}");
                    metrics::counter!(metric_name, &[("level", "warn"), ("error", "consumer"),])
                        .increment(1);
                    sleep(Duration::from_millis(100 * current_count.min(10))).await;
                }
            }

            None
        }

        KafkaError::MessageConsumptionFatal(code) => {
            error!("Fatal Kafka consumer error: {code:?}");
            metrics::counter!(metric_name, &[("level", "fatal"), ("error", "consumer"),])
                .increment(1);

            Some(e)
        }

        KafkaError::Global(code) => {
            match code {
                RDKafkaErrorCode::AllBrokersDown => {
                    warn!("All brokers down: {code:?} - waiting for reconnect");
                    metrics::counter!(
                        metric_name,
                        &[("level", "warn"), ("error", "all_brokers_down"),]
                    )
                    .increment(1);
                    sleep(Duration::from_secs(current_count.min(5))).await;
                }
                RDKafkaErrorCode::BrokerTransportFailure => {
                    warn!("Broker transport failure: {code:?} - waiting for reconnect");
                    metrics::counter!(
                        metric_name,
                        &[("level", "warn"), ("error", "broker_transport"),]
                    )
                    .increment(1);
                    sleep(Duration::from_secs(current_count.min(3))).await;
                }
                RDKafkaErrorCode::Authentication => {
                    error!("Authentication failed: {code:?}");
                    metrics::counter!(
                        metric_name,
                        &[("level", "fatal"), ("error", "authentication"),]
                    )
                    .increment(1);
                    return Some(e);
                }
                _ => {
                    warn!("Global Kafka error: {code:?}");
                    metrics::counter!(metric_name, &[("level", "warn"), ("error", "global"),])
                        .increment(1);
                    sleep(Duration::from_millis(500 * current_count.min(6))).await;
                }
            }

            None
        }

        KafkaError::Canceled => {
            info!("Consumer canceled - shutting down");
            metrics::counter!(metric_name, &[("level", "info"), ("error", "canceled"),])
                .increment(1);

            Some(e)
        }

        _ => {
            error!("Unexpected error: {e:#}");
            metrics::counter!(metric_name, &[("level", "fatal"), ("error", "unexpected"),])
                .increment(1);
            sleep(Duration::from_millis(100 * current_count.min(10))).await;

            None
        }
    }
}
