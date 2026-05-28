import { HealthCheckResult } from '../../types'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig, PipelineFactory } from './common-ingestion-consumer'
import { Scope } from './service-registry'

export interface CreateCommonIngestionConsumerArgs<S extends Record<string, object>> {
    config: CommonIngestionConsumerConfig
    /** Pre-built (not started) Scope holding the consumer-owned services. */
    scope: Scope<S>
    pipeline: PipelineFactory<S>
    healthcheck?: () => Promise<HealthCheckResult>
}

export function createCommonIngestionConsumer<S extends Record<string, object>>(
    args: CreateCommonIngestionConsumerArgs<S>
): CommonIngestionConsumer<S> {
    return new CommonIngestionConsumer<S>(args.config, args.scope, args.pipeline, args.healthcheck)
}
