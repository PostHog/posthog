import { HealthCheckResultOk } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from './common-ingestion-consumer'
import { composeConsumerLifecycle, createCommonIngestionConsumer } from './common-ingestion-consumer-builder'
import { ConsumerManagedService, newLifecycleBuilder } from './service-registry'

function makeOutputs(failures: string[] = []): IngestionOutputs<string> {
    return {
        checkTopics: jest.fn().mockResolvedValue(failures),
    } as unknown as IngestionOutputs<string>
}

function makeService(log: string[], label: string): ConsumerManagedService {
    return {
        start: jest.fn((): Promise<void> => {
            log.push(`${label}.start`)
            return Promise.resolve()
        }),
        stop: jest.fn((): Promise<void> => {
            log.push(`${label}.stop`)
            return Promise.resolve()
        }),
    }
}

function makeConfig(overrides: Partial<CommonIngestionConsumerConfig> = {}): CommonIngestionConsumerConfig {
    return {
        INGESTION_CONSUMER_GROUP_ID: 'g',
        INGESTION_CONSUMER_CONSUME_TOPIC: 't',
        INGESTION_PIPELINE: 'analytics',
        INGESTION_LANE: 'main',
        KAFKA_BATCH_START_LOGGING_ENABLED: false,
        ...overrides,
    }
}

describe('composeConsumerLifecycle', () => {
    it('starts services via the lifecycle, then verifies topics', async () => {
        const log: string[] = []
        const a = makeService(log, 'a')
        const b = makeService(log, 'b')
        const lifecycle = newLifecycleBuilder().register('a', a).register('b', b).build('consumer')

        const outputs = {
            checkTopics: jest.fn(() => {
                log.push('checkTopics')
                return Promise.resolve([])
            }),
        } as unknown as IngestionOutputs<string>

        const consumerLifecycle = composeConsumerLifecycle({
            lifecycle,
            outputs,
            promiseScheduler: new PromiseScheduler(),
            healthcheckFn: undefined,
        })

        await consumerLifecycle.onStart!()

        expect(log).toEqual(['a.start', 'b.start', 'checkTopics'])
    })

    it('rolls the lifecycle back when topic verification fails', async () => {
        const log: string[] = []
        const a = makeService(log, 'a')
        const lifecycle = newLifecycleBuilder().register('a', a).build('consumer')

        const consumerLifecycle = composeConsumerLifecycle({
            lifecycle,
            outputs: makeOutputs(['events', 'dlq']),
            promiseScheduler: new PromiseScheduler(),
            healthcheckFn: undefined,
        })

        await expect(consumerLifecycle.onStart!()).rejects.toThrow('Output topic verification failed')
        expect(log).toEqual(['a.start', 'a.stop'])
    })

    it('stops services in reverse, then drains the scheduler, on onStop', async () => {
        const log: string[] = []
        const a = makeService(log, 'a')
        const b = makeService(log, 'b')
        const lifecycle = newLifecycleBuilder().register('a', a).register('b', b).build('consumer')

        const scheduler = new PromiseScheduler()
        const drainSpy = jest.spyOn(scheduler, 'waitForAll').mockImplementation(() => {
            log.push('drain')
            return Promise.resolve([])
        })

        const consumerLifecycle = composeConsumerLifecycle({
            lifecycle,
            outputs: makeOutputs(),
            promiseScheduler: scheduler,
            healthcheckFn: undefined,
        })

        await consumerLifecycle.onStart!()
        await consumerLifecycle.onStop!()

        expect(log).toEqual(['a.start', 'b.start', 'b.stop', 'a.stop', 'drain'])
        expect(drainSpy).toHaveBeenCalledTimes(1)
    })

    it('exposes the supplied healthcheck function', () => {
        const fn = jest.fn().mockResolvedValue(new HealthCheckResultOk())

        const consumerLifecycle = composeConsumerLifecycle({
            lifecycle: newLifecycleBuilder().build('consumer'),
            outputs: makeOutputs(),
            promiseScheduler: new PromiseScheduler(),
            healthcheckFn: fn,
        })

        expect(consumerLifecycle.healthcheck).toBe(fn)
    })

    it('drains the promise scheduler in getBackgroundWork', async () => {
        const scheduler = new PromiseScheduler()
        const drainSpy = jest.spyOn(scheduler, 'waitForAll').mockResolvedValue([])

        const consumerLifecycle = composeConsumerLifecycle({
            lifecycle: newLifecycleBuilder().build('consumer'),
            outputs: makeOutputs(),
            promiseScheduler: scheduler,
            healthcheckFn: undefined,
        })

        await consumerLifecycle.getBackgroundWork!(scheduler)
        expect(drainSpy).toHaveBeenCalledTimes(1)
    })
})

describe('createCommonIngestionConsumer', () => {
    it('returns a CommonIngestionConsumer wired to the supplied lifecycle and pipeline', () => {
        const lifecycle = newLifecycleBuilder().build('consumer')
        const outputs = makeOutputs()
        const pipeline = { feed: jest.fn(), next: jest.fn() }

        const consumer = createCommonIngestionConsumer({
            config: makeConfig(),
            lifecycle,
            outputs,
            pipeline: () => pipeline,
        })

        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('passes the lifecycle services and outputs to the pipeline factory', () => {
        const a = makeService([], 'a')
        const lifecycle = newLifecycleBuilder().register('a', a).build('consumer')
        const outputs = makeOutputs()
        const factory = jest.fn().mockReturnValue({ feed: jest.fn(), next: jest.fn() })

        createCommonIngestionConsumer({
            config: makeConfig(),
            lifecycle,
            outputs,
            pipeline: factory,
        })

        expect(factory).toHaveBeenCalledTimes(1)
        const ctx = factory.mock.calls[0][0]
        expect(ctx.services).toBe(lifecycle.services)
        expect(ctx.outputs).toBe(outputs)
        expect(ctx.promiseScheduler).toBeDefined()
    })
})
