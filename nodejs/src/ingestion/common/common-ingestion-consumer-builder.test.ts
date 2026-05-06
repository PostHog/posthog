import { HealthCheckResultOk } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import {
    ConsumerManagedService,
    composeConsumerLifecycle,
    newCommonIngestionConsumer,
} from './common-ingestion-consumer-builder'

function makeOutputs(failures: string[] = []): IngestionOutputs<string> {
    return {
        checkTopics: jest.fn().mockResolvedValue(failures),
    } as unknown as IngestionOutputs<string>
}

function makeService(): ConsumerManagedService & { start: jest.Mock; stop: jest.Mock } {
    return {
        start: jest.fn().mockResolvedValue(undefined),
        stop: jest.fn().mockResolvedValue(undefined),
    }
}

function record(calls: string[], label: string): () => Promise<void> {
    return () => {
        calls.push(label)
        return Promise.resolve()
    }
}

describe('composeConsumerLifecycle', () => {
    it('starts services in registration order, then verifies topics, then runs onStart hooks', async () => {
        const calls: string[] = []
        const a: ConsumerManagedService = {
            start: jest.fn(record(calls, 'a.start')),
            stop: jest.fn().mockResolvedValue(undefined),
        }
        const b: ConsumerManagedService = {
            start: jest.fn(record(calls, 'b.start')),
            stop: jest.fn().mockResolvedValue(undefined),
        }
        const outputs = {
            checkTopics: jest.fn(() => {
                calls.push('checkTopics')
                return Promise.resolve([])
            }),
        } as unknown as IngestionOutputs<string>

        const lifecycle = composeConsumerLifecycle({
            services: { a, b },
            outputs,
            promiseScheduler: new PromiseScheduler(),
            onStartHooks: [record(calls, 'hook1'), record(calls, 'hook2')],
            onStopHooks: [],
            healthcheckFn: undefined,
        })

        await lifecycle.onStart!()

        expect(calls).toEqual(['a.start', 'b.start', 'checkTopics', 'hook1', 'hook2'])
    })

    it('stops in reverse: onStop hooks reversed, then services reversed, then drains scheduler', async () => {
        const calls: string[] = []
        const scheduler = new PromiseScheduler()
        const drainSpy = jest.spyOn(scheduler, 'waitForAll').mockImplementation(() => {
            calls.push('drain')
            return Promise.resolve([])
        })
        const a: ConsumerManagedService = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn(record(calls, 'a.stop')),
        }
        const b: ConsumerManagedService = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn(record(calls, 'b.stop')),
        }

        const lifecycle = composeConsumerLifecycle({
            services: { a, b },
            outputs: makeOutputs(),
            promiseScheduler: scheduler,
            onStartHooks: [],
            onStopHooks: [record(calls, 'stop1'), record(calls, 'stop2')],
            healthcheckFn: undefined,
        })

        await lifecycle.onStop!()

        expect(calls).toEqual(['stop2', 'stop1', 'b.stop', 'a.stop', 'drain'])
        expect(drainSpy).toHaveBeenCalledTimes(1)
    })

    it('throws when topic verification fails', async () => {
        const lifecycle = composeConsumerLifecycle({
            services: {},
            outputs: makeOutputs(['events', 'dlq']),
            promiseScheduler: new PromiseScheduler(),
            onStartHooks: [],
            onStopHooks: [],
            healthcheckFn: undefined,
        })

        await expect(lifecycle.onStart!()).rejects.toThrow(/events, dlq/)
    })

    it('does not run onStart hooks when topic verification fails', async () => {
        const hook = jest.fn()
        const lifecycle = composeConsumerLifecycle({
            services: {},
            outputs: makeOutputs(['oops']),
            promiseScheduler: new PromiseScheduler(),
            onStartHooks: [hook],
            onStopHooks: [],
            healthcheckFn: undefined,
        })

        await expect(lifecycle.onStart!()).rejects.toThrow()
        expect(hook).not.toHaveBeenCalled()
    })

    it('exposes the user-supplied healthcheck', async () => {
        const healthcheckFn = jest.fn().mockResolvedValue(new HealthCheckResultOk())
        const lifecycle = composeConsumerLifecycle({
            services: {},
            outputs: makeOutputs(),
            promiseScheduler: new PromiseScheduler(),
            onStartHooks: [],
            onStopHooks: [],
            healthcheckFn,
        })

        await lifecycle.healthcheck!()
        expect(healthcheckFn).toHaveBeenCalledTimes(1)
    })

    it('drains the promise scheduler in getBackgroundWork', async () => {
        const scheduler = new PromiseScheduler()
        const drainSpy = jest.spyOn(scheduler, 'waitForAll').mockResolvedValue([])

        const lifecycle = composeConsumerLifecycle({
            services: {},
            outputs: makeOutputs(),
            promiseScheduler: scheduler,
            onStartHooks: [],
            onStopHooks: [],
            healthcheckFn: undefined,
        })

        await lifecycle.getBackgroundWork!(new PromiseScheduler())
        expect(drainSpy).toHaveBeenCalledTimes(1)
    })
})

describe('newCommonIngestionConsumer phase transitions', () => {
    it('does not invoke the pipeline factory until build()', () => {
        const teamManager = makeService()
        const topHog = makeService()
        const outputs = makeOutputs()

        const factory = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })

        newCommonIngestionConsumer({
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'analytics',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
        })
            .withService('teamManager', teamManager)
            .withService('topHog', topHog)
            .setOutputs(outputs)
            .withPipeline(factory)

        expect(factory).toHaveBeenCalledTimes(0)
    })
})
