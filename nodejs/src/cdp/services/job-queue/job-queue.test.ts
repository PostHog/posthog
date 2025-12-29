import { DateTime } from 'luxon'

import { defaultConfig } from '~/config/config'
import { PluginsServerConfig } from '~/types'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../../_tests/fixtures'
import { createInvocation } from '../../utils/invocation-utils'
import { CyclotronJobQueue, JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS, getProducerMapping } from './job-queue'

describe('CyclotronJobQueue', () => {
    let config: PluginsServerConfig
    let mockConsumeBatch: jest.Mock

    const exampleHogFunction = createHogFunction({
        name: 'Test hog function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    beforeEach(() => {
        config = { ...defaultConfig }
        mockConsumeBatch = jest.fn()
    })

    describe('cyclotron', () => {
        beforeEach(() => {
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'postgres'
        })

        it('should initialise', () => {
            const queue = new CyclotronJobQueue(config, 'hog', mockConsumeBatch)
            expect(queue).toBeDefined()
            expect(queue['consumerMode']).toBe('postgres')
        })
    })

    describe('kafka', () => {
        beforeEach(() => {
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'kafka'
        })

        it('should initialise', () => {
            const queue = new CyclotronJobQueue(config, 'hog', mockConsumeBatch)
            expect(queue).toBeDefined()
            expect(queue['consumerMode']).toBe('kafka')
        })
    })

    describe('producer setup', () => {
        const buildQueue = (mapping: string, teamMapping?: string) => {
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'kafka'
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = mapping
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING = teamMapping || ''
            const queue = new CyclotronJobQueue(config, 'hog', mockConsumeBatch)
            queue['jobQueuePostgres'].startAsProducer = jest.fn()
            queue['jobQueueKafka'].startAsProducer = jest.fn()
            queue['jobQueuePostgres'].queueInvocations = jest.fn()
            queue['jobQueueKafka'].queueInvocations = jest.fn()
            return queue
        }

        it('should start only kafka producer if only kafka is mapped', async () => {
            const queue = buildQueue('*:kafka,hogflow:kafka')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).not.toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()
        })

        it('should start only postgres producer if only postgres is mapped', async () => {
            const queue = buildQueue('*:postgres,hogflow:postgres')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).not.toHaveBeenCalled()
        })

        it('should start both producers if both are mapped', async () => {
            const queue = buildQueue('*:postgres,hogflow:kafka')
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

        it('should account for team mapping', async () => {
            const queue = buildQueue('*:postgres', '1:*:kafka')
            await queue.startAsProducer()
            expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()
        })

        it.each([
            ['postgres', true],
            ['kafka', false],
        ])(
            'should route scheduled jobs to %s if force scheduled to postgres is enabled',
            async (_target, enforceRouting) => {
                config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES = enforceRouting
                const queue = buildQueue('*:kafka')
                await queue.startAsProducer()
                const invocations = [
                    {
                        ...createInvocation(
                            {
                                ...createHogExecutionGlobals(),
                                inputs: {},
                            },
                            exampleHogFunction
                        ),
                        queueScheduledAt: DateTime.now().plus({
                            milliseconds: JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS + 1000,
                        }),
                    },
                ]
                await queue.queueInvocations(invocations)

                if (enforceRouting) {
                    // With enforced routing and the main queue being kafka then both producers should be started
                    expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
                    expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()

                    expect(queue['jobQueuePostgres'].queueInvocations).toHaveBeenCalledWith(invocations)
                    expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith([])
                } else {
                    // Without enforced routing only the kafka producer should be started
                    expect(queue['jobQueuePostgres'].startAsProducer).not.toHaveBeenCalled()
                    expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()

                    expect(queue['jobQueuePostgres'].queueInvocations).toHaveBeenCalledWith([])
                    expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith(invocations)
                }
            }
        )

        it('should not route scheduled jobs to postgres if they are not scheduled far enough in the future', async () => {
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES = true

            const queue = buildQueue('*:kafka')
            await queue.startAsProducer()
            const invocations = [
                {
                    ...createInvocation(
                        {
                            ...createHogExecutionGlobals(),
                            inputs: {},
                        },
                        exampleHogFunction
                    ),
                    queueScheduledAt: DateTime.now().plus({
                        milliseconds: JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS - 1000,
                    }),
                },
            ]
            await queue.queueInvocations(invocations)

            // With enforced routing and the main queue being kafka then both producers should be started
            expect(queue['jobQueuePostgres'].startAsProducer).toHaveBeenCalled()
            expect(queue['jobQueueKafka'].startAsProducer).toHaveBeenCalled()

            expect(queue['jobQueuePostgres'].queueInvocations).toHaveBeenCalledWith([])
            expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith(invocations)
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
            '*:kafka:0.5,hog:kafka:1,hogflow:postgres:0.1',
            {
                '*': { target: 'kafka', percentage: 0.5 },
                hog: { target: 'kafka', percentage: 1 },
                hogflow: { target: 'postgres', percentage: 0.1 },
            },
        ],
    ])('should return the correct mapping for %s', (mapping, expected) => {
        expect(getProducerMapping(mapping)).toEqual(expected)
    })

    it.each([
        ['*:kafkatypo', 'Invalid mapping: *:kafkatypo - target kafkatypo must be one of postgres, kafka'],
        ['hog:kafkatypo', 'Invalid mapping: hog:kafkatypo - target kafkatypo must be one of postgres, kafka'],
        [
            'hog:kafka,hogflow:postgres,*:kafkatypo',
            'Invalid mapping: *:kafkatypo - target kafkatypo must be one of postgres, kafka',
        ],
        [
            'wrong_queue:kafka',
            'Invalid mapping: wrong_queue:kafka - queue wrong_queue must be one of *, hog, hogoverflow, hogflow',
        ],
        ['hog:kafka:1.1', 'Invalid mapping: hog:kafka:1.1 - percentage 1.1 must be 0 < x <= 1'],
        ['hog:kafka', 'No mapping for the default queue for example: *:postgres'],
    ])('should throw for bad values for %s', (mapping, error) => {
        expect(() => getProducerMapping(mapping)).toThrow(error)
    })
})
