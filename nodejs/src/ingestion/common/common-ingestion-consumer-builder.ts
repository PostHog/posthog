import { HealthCheckResult } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import {
    CommonIngestionConsumer,
    CommonIngestionConsumerConfig,
    IngestionBatchingPipeline,
    IngestionPipelineLifecycle,
} from './common-ingestion-consumer'
import { Lifecycle, ServiceMap, StartedLifecycle } from './service-registry'

export interface PipelineFactoryContext<S extends ServiceMap, O extends string> {
    services: S
    outputs: IngestionOutputs<O>
    promiseScheduler: PromiseScheduler
}

export type PipelineFactory<S extends ServiceMap, O extends string> = (
    ctx: PipelineFactoryContext<S, O>
) => IngestionBatchingPipeline

export interface CreateCommonIngestionConsumerArgs<S extends ServiceMap, O extends string> {
    config: CommonIngestionConsumerConfig
    /**
     * Pre-built service lifecycle. The consumer drives its `start()` / `stop()`
     * during the consumer's own start/stop, and its services are passed to
     * the pipeline factory (stripped of `start`/`stop`, so the pipeline can't
     * accidentally tear an individual service down).
     */
    lifecycle: Lifecycle<S>
    outputs: IngestionOutputs<O>
    pipeline: PipelineFactory<S, O>
    healthcheck?: () => Promise<HealthCheckResult>
}

/**
 * Wire a `Lifecycle` + outputs + pipeline factory into a runnable
 * `CommonIngestionConsumer`. On start: brings up services via the lifecycle,
 * then verifies output topics (rolling the lifecycle back if verification
 * fails). On stop: tears the lifecycle down in reverse and drains the
 * background promise scheduler.
 */
export function createCommonIngestionConsumer<S extends ServiceMap, O extends string>(
    args: CreateCommonIngestionConsumerArgs<S, O>
): CommonIngestionConsumer {
    const { config, lifecycle, outputs, pipeline: pipelineFactory, healthcheck } = args

    const promiseScheduler = new PromiseScheduler()
    const pipeline = pipelineFactory({ services: lifecycle.services, outputs, promiseScheduler })

    const consumerLifecycle = composeConsumerLifecycle({
        lifecycle,
        outputs,
        promiseScheduler,
        healthcheckFn: healthcheck,
    })

    return new CommonIngestionConsumer(config, pipeline, consumerLifecycle)
}

interface ComposeConsumerLifecycleArgs<S extends ServiceMap, O extends string> {
    lifecycle: Lifecycle<S>
    outputs: IngestionOutputs<O>
    promiseScheduler: PromiseScheduler
    healthcheckFn: (() => Promise<HealthCheckResult>) | undefined
}

export function composeConsumerLifecycle<S extends ServiceMap, O extends string>({
    lifecycle,
    outputs,
    promiseScheduler,
    healthcheckFn,
}: ComposeConsumerLifecycleArgs<S, O>): IngestionPipelineLifecycle {
    let started: StartedLifecycle<S> | undefined

    return {
        onStart: async () => {
            started = await lifecycle.start()
            try {
                const failures = await outputs.checkTopics()
                if (failures.length > 0) {
                    throw new Error(`Output topic verification failed for: ${failures.join(', ')}`)
                }
            } catch (err) {
                // Topic verification failed after services started — roll the
                // lifecycle back so we don't leak resources, then propagate.
                try {
                    await started.stop()
                } catch {
                    // best-effort cleanup; propagate the original error
                }
                started = undefined
                throw err
            }
        },
        onStop: async () => {
            if (started) {
                await started.stop()
                started = undefined
            }
            await promiseScheduler.waitForAll()
        },
        healthcheck: healthcheckFn,
        getBackgroundWork: async () => {
            await promiseScheduler.waitForAll()
        },
    }
}
