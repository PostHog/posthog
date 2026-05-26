import { HealthCheckResult } from '../../types'
import {
    CommonIngestionConsumer,
    CommonIngestionConsumerConfig,
    PipelineFactory,
    ServicesWithOutputs,
} from './common-ingestion-consumer'
import { Lifecycle } from './service-registry'

export interface CreateCommonIngestionConsumerArgs<S extends ServicesWithOutputs<O>, O extends string> {
    config: CommonIngestionConsumerConfig
    /**
     * Pre-built (not started) Lifecycle holding the consumer-owned services.
     * Must expose `outputs` in its services map — the consumer reads it
     * for topic verification and threads it through to the pipeline
     * factory.
     */
    lifecycle: Lifecycle<S>
    pipeline: PipelineFactory<S, O>
    healthcheck?: () => Promise<HealthCheckResult>
}

export function createCommonIngestionConsumer<S extends ServicesWithOutputs<O>, O extends string>(
    args: CreateCommonIngestionConsumerArgs<S, O>
): CommonIngestionConsumer<S, O> {
    return new CommonIngestionConsumer<S, O>(args.config, args.lifecycle, args.pipeline, args.healthcheck)
}
