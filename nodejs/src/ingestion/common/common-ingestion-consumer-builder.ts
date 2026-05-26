import { HealthCheckResult } from '../../types'
import {
    CommonIngestionConsumer,
    CommonIngestionConsumerConfig,
    ContainerWithOutputs,
    PipelineFactory,
} from './common-ingestion-consumer'
import { Scope } from './service-registry'

export interface CreateCommonIngestionConsumerArgs<S extends ContainerWithOutputs<O>, O extends string> {
    config: CommonIngestionConsumerConfig
    /**
     * Pre-built (not started) Scope holding the consumer-owned services.
     * Must expose `outputs` in its services map — the consumer reads it
     * for topic verification and threads it through to the pipeline
     * factory.
     */
    scope: Scope<S>
    pipeline: PipelineFactory<S, O>
    healthcheck?: () => Promise<HealthCheckResult>
}

export function createCommonIngestionConsumer<S extends ContainerWithOutputs<O>, O extends string>(
    args: CreateCommonIngestionConsumerArgs<S, O>
): CommonIngestionConsumer<S, O> {
    return new CommonIngestionConsumer<S, O>(args.config, args.scope, args.pipeline, args.healthcheck)
}
