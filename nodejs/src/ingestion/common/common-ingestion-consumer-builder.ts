import { HealthCheckResult } from '../../types'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig, PipelineFactory } from './common-ingestion-consumer'
import { Lifecycle } from './service-registry'

export interface CreateCommonIngestionConsumerArgs<S extends Record<string, object>, O extends string> {
    config: CommonIngestionConsumerConfig
    /**
     * Pre-built (not started) Lifecycle holding the consumer-owned services.
     * The consumer brings it up on `start()`, hands the started services
     * to the pipeline factory, and stops it on `stop()`.
     */
    lifecycle: Lifecycle<S>
    outputs: IngestionOutputs<O>
    pipeline: PipelineFactory<S, O>
    healthcheck?: () => Promise<HealthCheckResult>
}

export function createCommonIngestionConsumer<S extends Record<string, object>, O extends string>(
    args: CreateCommonIngestionConsumerArgs<S, O>
): CommonIngestionConsumer<S, O> {
    return new CommonIngestionConsumer<S, O>(args.config, args.lifecycle, args.outputs, args.pipeline, args.healthcheck)
}
