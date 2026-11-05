import { LogsIngestionConsumerConfig, TracesIngestionConsumerConfig } from '../config'
import { LogsIngestionConsumer, LogsIngestionConsumerDeps } from '../logs-ingestion-consumer'
import { TracesIngestionConsumer, TracesIngestionConsumerDeps } from '../traces-ingestion-consumer'
import { LogsIngestionFrameworkConsumer } from './logs-ingestion-framework-consumer'
import { TracesIngestionFrameworkConsumer } from './traces-ingestion-framework-consumer'

export function createLogsIngestionConsumer(
    config: LogsIngestionConsumerConfig,
    deps: LogsIngestionConsumerDeps
): LogsIngestionConsumer | LogsIngestionFrameworkConsumer {
    return config.LOGS_INGESTION_USE_FRAMEWORK
        ? new LogsIngestionFrameworkConsumer(config, deps)
        : new LogsIngestionConsumer(config, deps)
}

export function createTracesIngestionConsumer(
    config: LogsIngestionConsumerConfig & TracesIngestionConsumerConfig,
    deps: TracesIngestionConsumerDeps
): TracesIngestionConsumer | TracesIngestionFrameworkConsumer {
    return config.TRACES_INGESTION_USE_FRAMEWORK
        ? new TracesIngestionFrameworkConsumer(config, deps)
        : new TracesIngestionConsumer(config, deps)
}
