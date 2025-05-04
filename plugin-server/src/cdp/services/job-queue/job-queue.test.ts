import { defaultConfig } from '~/src/config/config'
import { PluginsServerConfig } from '~/src/types'

import { HogFunctionManagerService } from '../hog-function-manager.service'
import { CyclotronJobQueue, getProducerMapping } from './job-queue'

describe('CyclotronJobQueue', () => {
    let config: PluginsServerConfig
    let mockHogFunctionManager: jest.Mocked<HogFunctionManagerService>
    let mockConsumeBatch: jest.Mock

    beforeEach(() => {
        config = { ...defaultConfig }
        mockHogFunctionManager = {} as jest.Mocked<HogFunctionManagerService>
        mockConsumeBatch = jest.fn()
    })

    describe('cyclotron', () => {
        beforeEach(() => {
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'postgres'
        })

        it('should initialise', () => {
            const queue = new CyclotronJobQueue(config, 'hog', mockHogFunctionManager, mockConsumeBatch)
            expect(queue).toBeDefined()
            expect(queue['consumerMode']).toBe('postgres')
        })
    })

    describe('kafka', () => {
        beforeEach(() => {
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'kafka'
        })

        it('should initialise', () => {
            const queue = new CyclotronJobQueue(config, 'hog', mockHogFunctionManager, mockConsumeBatch)
            expect(queue).toBeDefined()
            expect(queue['consumerMode']).toBe('kafka')
        })
    })

    describe('producer setup', () => {
        const buildQueue = (mapping: string) => {
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'kafka'
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = mapping
            const queue = new CyclotronJobQueue(config, 'hog', mockHogFunctionManager, mockConsumeBatch)
            queue['jobQueuePostgres'].startAsProducer = jest.fn()
            queue['jobQueueKafka'].startAsProducer = jest.fn()
            return queue
        }

        it('should start only kafka producer if only kafka is mapped', async () => {
            const queue = buildQueue('*:kafka,fetch:kafka')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).not.toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()
        })

        it('should start only postgres producer if only postgres is mapped', async () => {
            const queue = buildQueue('*:postgres,fetch:postgres')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).not.toHaveBeenCalled()
        })

        it('should start both producers if both are mapped', async () => {
            const queue = buildQueue('*:postgres,fetch:kafka')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()
        })

        it('should start both producers if a percentage is mapped', async () => {
            const queue = buildQueue('*:postgres:0.5')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()
        })
    })
})

describe('getProducerMapping', () => {
    it.each([
        [
            '*:kafka',
            {
                '*': { target: 'kafka', percentage: 1 },
            },
        ],
        [
            '*:kafka:0.5,hog:kafka:1,fetch:postgres:0.1',
            {
                '*': { target: 'kafka', percentage: 0.5 },
                hog: { target: 'kafka', percentage: 1 },
                fetch: { target: 'postgres', percentage: 0.1 },
            },
        ],
    ])('should return the correct mapping for %s', (mapping, expected) => {
        expect(getProducerMapping(mapping)).toEqual(expected)
    })

    it.each([
        ['*:kafkatypo', 'Invalid mapping: *:kafkatypo - target kafkatypo must be one of postgres, kafka'],
        ['hog:kafkatypo', 'Invalid mapping: hog:kafkatypo - target kafkatypo must be one of postgres, kafka'],
        [
            'hog:kafka,fetch:postgres,*:kafkatypo',
            'Invalid mapping: *:kafkatypo - target kafkatypo must be one of postgres, kafka',
        ],
        [
            'wrong_queue:kafka',
            'Invalid mapping: wrong_queue:kafka - queue wrong_queue must be one of *, hog, fetch, plugin',
        ],
        ['hog:kafka:1.1', 'Invalid mapping: hog:kafka:1.1 - percentage 1.1 must be 0 < x <= 1'],
        ['hog:kafka', 'No mapping for the default queue for example: *:postgres'],
    ])('should throw for bad values for %s', (mapping, error) => {
        expect(() => getProducerMapping(mapping)).toThrow(error)
    })
})
