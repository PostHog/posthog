import { HealthCheckResult } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import {
    CommonIngestionConsumer,
    CommonIngestionConsumerConfig,
    IngestionBatchingPipeline,
    IngestionPipelineLifecycle,
} from './common-ingestion-consumer'

/**
 * The lifecycle contract honored by the builder for every registered service.
 *
 * Both methods are optional: services without lifecycle (e.g., a `TeamManager`
 * that's pure in-memory cache) simply omit them. The builder calls `start()`
 * in registration order and `stop()` in reverse on the consumer's own lifecycle.
 *
 * Note: `withService` doesn't constrain its `T` parameter to this interface —
 * TypeScript's "weak type" check rejects objects that share no properties with
 * an all-optional interface, which would block legitimate lifecycle-less
 * services. The builder's runtime composition coerces every entry through
 * this shape anyway, so the contract is enforced at the call sites of
 * `service.start?.()` / `service.stop?.()`, not at registration.
 */
export interface ConsumerManagedService {
    start?(): Promise<void>
    stop?(): Promise<void>
}

export interface PipelineFactoryContext<S, O extends string> {
    outputs: IngestionOutputs<O>
    services: S
    promiseScheduler: PromiseScheduler
}

export type PipelineFactory<S, O extends string> = (ctx: PipelineFactoryContext<S, O>) => IngestionBatchingPipeline

type ServiceMap = Record<string, unknown>

// `keyof EmptyServiceMap` is `never`, which makes the duplicate-name check in `withService`
// behave correctly when no services have been registered yet. Using `Record<string, never>`
// here would make `keyof` be `string`, blocking every name as a duplicate.
// eslint-disable-next-line @typescript-eslint/no-empty-object-type
type EmptyServiceMap = {}

interface BuilderState<S extends ServiceMap, O extends string> {
    config: CommonIngestionConsumerConfig
    services: S
    outputs: IngestionOutputs<O>
    pipelineFactory: PipelineFactory<S, O>
    onStartHooks: Array<() => Promise<void>>
    onStopHooks: Array<() => Promise<void>>
    healthcheckFn: (() => Promise<HealthCheckResult>) | undefined
    overrides: { groupId?: string; topic?: string }
}

export class ConsumerNeedsOutputsBuilder<S extends ServiceMap = EmptyServiceMap> {
    constructor(
        private readonly config: CommonIngestionConsumerConfig,
        private readonly services: S
    ) {}

    withService<Name extends string, T>(
        name: Name & (Name extends keyof S ? never : Name),
        service: T
    ): ConsumerNeedsOutputsBuilder<S & Record<Name, T>> {
        const next = { ...this.services, [name]: service } as S & Record<Name, T>
        return new ConsumerNeedsOutputsBuilder(this.config, next)
    }

    setOutputs<O extends string>(outputs: IngestionOutputs<O>): ConsumerNeedsPipelineBuilder<S, O> {
        return new ConsumerNeedsPipelineBuilder(this.config, this.services, outputs)
    }
}

export class ConsumerNeedsPipelineBuilder<S extends ServiceMap, O extends string> {
    constructor(
        private readonly config: CommonIngestionConsumerConfig,
        private readonly services: S,
        private readonly outputs: IngestionOutputs<O>
    ) {}

    withPipeline(factory: PipelineFactory<S, O>): ConsumerBuilder<S, O> {
        return new ConsumerBuilder({
            config: this.config,
            services: this.services,
            outputs: this.outputs,
            pipelineFactory: factory,
            onStartHooks: [],
            onStopHooks: [],
            healthcheckFn: undefined,
            overrides: {},
        })
    }
}

export class ConsumerBuilder<S extends ServiceMap, O extends string> {
    constructor(private readonly state: BuilderState<S, O>) {}

    onStart(fn: () => Promise<void>): ConsumerBuilder<S, O> {
        return new ConsumerBuilder({
            ...this.state,
            onStartHooks: [...this.state.onStartHooks, fn],
        })
    }

    onStop(fn: () => Promise<void>): ConsumerBuilder<S, O> {
        return new ConsumerBuilder({
            ...this.state,
            onStopHooks: [...this.state.onStopHooks, fn],
        })
    }

    healthcheck(fn: () => Promise<HealthCheckResult>): ConsumerBuilder<S, O> {
        if (this.state.healthcheckFn) {
            throw new Error('healthcheck() can only be called once')
        }
        return new ConsumerBuilder({ ...this.state, healthcheckFn: fn })
    }

    overrideGroupId(groupId: string): ConsumerBuilder<S, O> {
        return new ConsumerBuilder({
            ...this.state,
            overrides: { ...this.state.overrides, groupId },
        })
    }

    overrideTopic(topic: string): ConsumerBuilder<S, O> {
        return new ConsumerBuilder({
            ...this.state,
            overrides: { ...this.state.overrides, topic },
        })
    }

    build(): CommonIngestionConsumer {
        const { config, services, outputs, pipelineFactory, onStartHooks, onStopHooks, healthcheckFn, overrides } =
            this.state

        const promiseScheduler = new PromiseScheduler()
        const pipeline = pipelineFactory({ outputs, services, promiseScheduler })

        const lifecycle = composeConsumerLifecycle({
            services,
            outputs,
            promiseScheduler,
            onStartHooks,
            onStopHooks,
            healthcheckFn,
        })

        return new CommonIngestionConsumer(config, pipeline, lifecycle, {
            INGESTION_CONSUMER_GROUP_ID: overrides.groupId,
            INGESTION_CONSUMER_CONSUME_TOPIC: overrides.topic,
        })
    }
}

export function newCommonIngestionConsumer(
    config: CommonIngestionConsumerConfig
): ConsumerNeedsOutputsBuilder<EmptyServiceMap> {
    return new ConsumerNeedsOutputsBuilder(config, {})
}

export interface ComposeLifecycleArgs<S extends ServiceMap, O extends string> {
    services: S
    outputs: IngestionOutputs<O>
    promiseScheduler: PromiseScheduler
    onStartHooks: Array<() => Promise<void>>
    onStopHooks: Array<() => Promise<void>>
    healthcheckFn: (() => Promise<HealthCheckResult>) | undefined
}

export function composeConsumerLifecycle<S extends ServiceMap, O extends string>({
    services,
    outputs,
    promiseScheduler,
    onStartHooks,
    onStopHooks,
    healthcheckFn,
}: ComposeLifecycleArgs<S, O>): IngestionPipelineLifecycle {
    const serviceEntries = Object.entries(services) as Array<[string, ConsumerManagedService | undefined]>

    return {
        onStart: async () => {
            for (const [, service] of serviceEntries) {
                if (service?.start) {
                    await service.start()
                }
            }
            const failures = await outputs.checkTopics()
            if (failures.length > 0) {
                throw new Error(`Output topic verification failed for: ${failures.join(', ')}`)
            }
            for (const hook of onStartHooks) {
                await hook()
            }
        },
        onStop: async () => {
            for (const hook of [...onStopHooks].reverse()) {
                await hook()
            }
            for (const [, service] of [...serviceEntries].reverse()) {
                if (service?.stop) {
                    await service.stop()
                }
            }
            await promiseScheduler.waitForAll()
        },
        healthcheck: healthcheckFn,
        getBackgroundWork: async () => {
            await promiseScheduler.waitForAll()
        },
    }
}
