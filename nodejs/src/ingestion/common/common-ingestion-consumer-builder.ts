import { HealthCheckResult } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import {
    CommonIngestionConsumer,
    CommonIngestionConsumerConfig,
    IngestionBatchingPipeline,
    IngestionPipelineLifecycle,
} from './common-ingestion-consumer'

export interface PipelineFactoryContext<O extends string> {
    outputs: IngestionOutputs<O>
    promiseScheduler: PromiseScheduler
}

export type PipelineFactory<O extends string> = (ctx: PipelineFactoryContext<O>) => IngestionBatchingPipeline

export interface CreateCommonIngestionConsumerArgs<O extends string> {
    config: CommonIngestionConsumerConfig
    outputs: IngestionOutputs<O>
    pipeline: PipelineFactory<O>
    healthcheck?: () => Promise<HealthCheckResult>
}

/**
 * Wire outputs + a pipeline factory into a runnable `CommonIngestionConsumer`.
 * Service lifecycles (shared or per-consumer) live outside this factory —
 * the caller starts services before constructing the consumer and stops them
 * after. On start: verifies output topics. On stop: drains the background
 * promise scheduler.
 */
export function createCommonIngestionConsumer<O extends string>(
    args: CreateCommonIngestionConsumerArgs<O>
): CommonIngestionConsumer {
    const { config, outputs, pipeline: pipelineFactory, healthcheck } = args

    const promiseScheduler = new PromiseScheduler()
    const pipeline = pipelineFactory({ outputs, promiseScheduler })

    const consumerLifecycle = composeConsumerLifecycle({
        outputs,
        promiseScheduler,
        healthcheckFn: healthcheck,
    })

    return new CommonIngestionConsumer(config, pipeline, consumerLifecycle)
}

interface ComposeConsumerLifecycleArgs<O extends string> {
    outputs: IngestionOutputs<O>
    promiseScheduler: PromiseScheduler
    healthcheckFn: (() => Promise<HealthCheckResult>) | undefined
}

export function composeConsumerLifecycle<O extends string>({
    outputs,
    promiseScheduler,
    healthcheckFn,
}: ComposeConsumerLifecycleArgs<O>): IngestionPipelineLifecycle {
    return {
        onStart: async () => {
            const failures = await outputs.checkTopics()
            if (failures.length > 0) {
                throw new Error(`Output topic verification failed for: ${failures.join(', ')}`)
            }
        },
        onStop: async () => {
            await promiseScheduler.waitForAll()
        },
        healthcheck: healthcheckFn,
        getBackgroundWork: async () => {
            await promiseScheduler.waitForAll()
        },
    }
}
