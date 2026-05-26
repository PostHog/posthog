import { HealthCheckResultOk } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from './common-ingestion-consumer'
import { composeConsumerLifecycle, createCommonIngestionConsumer } from './common-ingestion-consumer-builder'

function makeOutputs(failures: string[] = []): IngestionOutputs<string> {
    return {
        checkTopics: jest.fn().mockResolvedValue(failures),
    } as unknown as IngestionOutputs<string>
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
    it('verifies output topics on start', async () => {
        const outputs = makeOutputs()

        const consumerLifecycle = composeConsumerLifecycle({
            outputs,
            promiseScheduler: new PromiseScheduler(),
            healthcheckFn: undefined,
        })

        await consumerLifecycle.onStart!()
        expect(outputs.checkTopics).toHaveBeenCalledTimes(1)
    })

    it('throws on start when topic verification fails', async () => {
        const consumerLifecycle = composeConsumerLifecycle({
            outputs: makeOutputs(['events', 'dlq']),
            promiseScheduler: new PromiseScheduler(),
            healthcheckFn: undefined,
        })

        await expect(consumerLifecycle.onStart!()).rejects.toThrow('Output topic verification failed')
    })

    it('drains the promise scheduler on stop', async () => {
        const scheduler = new PromiseScheduler()
        const drainSpy = jest.spyOn(scheduler, 'waitForAll').mockResolvedValue([])

        const consumerLifecycle = composeConsumerLifecycle({
            outputs: makeOutputs(),
            promiseScheduler: scheduler,
            healthcheckFn: undefined,
        })

        await consumerLifecycle.onStop!()
        expect(drainSpy).toHaveBeenCalledTimes(1)
    })

    it('exposes the supplied healthcheck function', () => {
        const fn = jest.fn().mockResolvedValue(new HealthCheckResultOk())

        const consumerLifecycle = composeConsumerLifecycle({
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
            outputs: makeOutputs(),
            promiseScheduler: scheduler,
            healthcheckFn: undefined,
        })

        await consumerLifecycle.getBackgroundWork!(scheduler)
        expect(drainSpy).toHaveBeenCalledTimes(1)
    })
})

describe('createCommonIngestionConsumer', () => {
    it('returns a CommonIngestionConsumer wired to the supplied pipeline', () => {
        const pipeline = { feed: jest.fn(), next: jest.fn() }

        const consumer = createCommonIngestionConsumer({
            config: makeConfig(),
            outputs: makeOutputs(),
            pipeline: () => pipeline,
        })

        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('passes outputs and a promise scheduler to the pipeline factory', () => {
        const outputs = makeOutputs()
        const factory = jest.fn().mockReturnValue({ feed: jest.fn(), next: jest.fn() })

        createCommonIngestionConsumer({
            config: makeConfig(),
            outputs,
            pipeline: factory,
        })

        expect(factory).toHaveBeenCalledTimes(1)
        const ctx = factory.mock.calls[0][0]
        expect(ctx.outputs).toBe(outputs)
        expect(ctx.promiseScheduler).toBeDefined()
    })
})
