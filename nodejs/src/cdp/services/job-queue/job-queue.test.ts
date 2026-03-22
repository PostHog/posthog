import { DateTime } from 'luxon'

import { defaultConfig } from '~/config/config'
import { PluginsServerConfig } from '~/types'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../../_tests/fixtures'
import { CyclotronJobInvocationResult, CyclotronJobQueueSource } from '../../types'
import { createInvocation } from '../../utils/invocation-utils'
import {
    CyclotronJobQueue,
    JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS,
    getProducerMapping,
    getProducerTeamMapping,
} from './job-queue'

describe('CyclotronJobQueue', () => {
    let config: PluginsServerConfig
    const exampleHogFunction = createHogFunction({
        name: 'Test hog function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    beforeEach(() => {
        config = { ...defaultConfig }
    })

    it('should initialise', () => {
        const queue = new CyclotronJobQueue(config.CONSUMER_BATCH_SIZE, config.KAFKA_CLIENT_RACK, config)
        expect(queue).toBeDefined()
    })

    describe('producer setup', () => {
        const buildQueue = (mapping: string, teamMapping?: string) => {
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = mapping
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING = teamMapping || ''
            const queue = new CyclotronJobQueue(config.CONSUMER_BATCH_SIZE, config.KAFKA_CLIENT_RACK, config)
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

        it('should start both producers if split routing is mapped', async () => {
            const queue = buildQueue('*:postgres:0.5,*:kafka:0.5')
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

        describe('team-specific percentage routing', () => {
            let queue: CyclotronJobQueue

            beforeEach(async () => {
                queue = buildQueue('*:kafka', '79155:*:kafka,79155:hog:postgres-v2:0.001')
                queue['jobQueuePostgresV2'] = {
                    startAsProducer: jest.fn(),
                    queueInvocations: jest.fn(),
                } as any
                await queue.startAsProducer()
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            const team79155HogFunction = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                team_id: 79155,
            })

            it('should route hog jobs to postgres-v2 when roll is below percentage', async () => {
                jest.spyOn(Math, 'random').mockReturnValue(0.0005)
                const invocation = createInvocation(
                    { ...createHogExecutionGlobals(), inputs: {} },
                    team79155HogFunction
                )
                await queue.queueInvocations([invocation])

                expect(queue['jobQueuePostgresV2']!.queueInvocations).toHaveBeenCalledWith([
                    expect.objectContaining({ teamId: 79155, queue: 'hog' }),
                ])
                expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith([])
            })

            it('should route hog jobs to kafka when roll exceeds percentage', async () => {
                jest.spyOn(Math, 'random').mockReturnValue(0.5)
                const invocation = createInvocation(
                    { ...createHogExecutionGlobals(), inputs: {} },
                    team79155HogFunction
                )
                await queue.queueInvocations([invocation])

                expect(queue['jobQueuePostgresV2']!.queueInvocations).toHaveBeenCalledWith([])
                expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith([
                    expect.objectContaining({ teamId: 79155, queue: 'hog' }),
                ])
            })

            it('should route non-hog queues to the team default', async () => {
                const invocation = {
                    ...createInvocation({ ...createHogExecutionGlobals(), inputs: {} }, team79155HogFunction),
                    queue: 'hogflow' as const,
                }
                await queue.queueInvocations([invocation])

                expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith([
                    expect.objectContaining({ teamId: 79155, queue: 'hogflow' }),
                ])
                expect(queue['jobQueuePostgresV2']!.queueInvocations).toHaveBeenCalledWith([])
            })

            it('should not affect other teams', async () => {
                jest.spyOn(Math, 'random').mockReturnValue(0.0005)
                const invocation = createInvocation(
                    { ...createHogExecutionGlobals(), inputs: {} },
                    exampleHogFunction // team_id defaults to 1
                )
                await queue.queueInvocations([invocation])

                expect(queue['jobQueueKafka'].queueInvocations).toHaveBeenCalledWith([
                    expect.objectContaining({ teamId: 1, queue: 'hog' }),
                ])
                expect(queue['jobQueuePostgresV2']!.queueInvocations).toHaveBeenCalledWith([])
            })
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

    describe('queueInvocationResults', () => {
        const buildQueue = (mapping: string) => {
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = mapping
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING = ''
            const queue = new CyclotronJobQueue(config.CONSUMER_BATCH_SIZE, config.KAFKA_CLIENT_RACK, config)

            // Mock all sub-queue methods
            queue['jobQueuePostgres'].queueInvocations = jest.fn()
            queue['jobQueuePostgres'].queueInvocationResults = jest.fn()
            queue['jobQueuePostgres'].releaseInvocations = jest.fn()
            queue['jobQueueKafka'].queueInvocations = jest.fn()
            queue['jobQueueKafka'].queueInvocationResults = jest.fn()
            queue['jobQueuePostgresV2'] = {
                queueInvocations: jest.fn(),
                queueInvocationResults: jest.fn(),
                releaseInvocations: jest.fn(),
            } as any

            return queue
        }

        const createResult = (queueSource: CyclotronJobQueueSource): CyclotronJobInvocationResult => ({
            invocation: {
                ...createInvocation({ ...createHogExecutionGlobals(), inputs: {} }, exampleHogFunction),
                queueSource,
            },
            finished: false,
            error: null,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            warehouseWebhookPayloads: [],
        })

        it.each([
            {
                scenario: 'postgres-v2 source routed to postgres target',
                mapping: '*:postgres',
                queueSource: 'postgres-v2' as const,
                expectReleasedFrom: 'jobQueuePostgresV2',
            },
            {
                scenario: 'postgres source routed to postgres-v2 target',
                mapping: '*:postgres-v2',
                queueSource: 'postgres' as const,
                expectReleasedFrom: 'jobQueuePostgres',
            },
            {
                scenario: 'postgres source routed to kafka target',
                mapping: '*:kafka',
                queueSource: 'postgres' as const,
                expectReleasedFrom: 'jobQueuePostgres',
            },
            {
                scenario: 'postgres-v2 source routed to kafka target',
                mapping: '*:kafka',
                queueSource: 'postgres-v2' as const,
                expectReleasedFrom: 'jobQueuePostgresV2',
            },
        ])(
            'should release source job when cross-routing: $scenario',
            async ({ mapping, queueSource, expectReleasedFrom }) => {
                const queue = buildQueue(mapping)
                const result = createResult(queueSource)

                await queue.queueInvocationResults([result])

                expect(
                    (queue[expectReleasedFrom as keyof typeof queue] as any).releaseInvocations
                ).toHaveBeenCalledTimes(1)
            }
        )

        it.each([
            { mapping: '*:postgres', queueSource: 'postgres' as const },
            { mapping: '*:postgres-v2', queueSource: 'postgres-v2' as const },
        ])(
            'should not release when source matches target: $mapping / $queueSource',
            async ({ mapping, queueSource }) => {
                const queue = buildQueue(mapping)
                const result = createResult(queueSource)

                await queue.queueInvocationResults([result])

                // Should update, not create+release
                expect(queue['jobQueuePostgres'].releaseInvocations).not.toHaveBeenCalled()
                expect(queue['jobQueuePostgresV2']!.releaseInvocations).not.toHaveBeenCalled()
            }
        )
    })
})

describe('getProducerMapping', () => {
    it.each([
        [
            '*:kafka',
            {
                '*': [{ target: 'kafka', percentage: 1 }],
            },
        ],
        [
            '*:kafka:0.5,*:postgres:0.5,hog:kafka,hogflow:postgres:0.1,hogflow:kafka:0.9',
            {
                '*': [
                    { target: 'kafka', percentage: 0.5 },
                    { target: 'postgres', percentage: 0.5 },
                ],
                hog: [{ target: 'kafka', percentage: 1 }],
                hogflow: [
                    { target: 'postgres', percentage: 0.1 },
                    { target: 'kafka', percentage: 0.9 },
                ],
            },
        ],
    ])('should return the correct mapping for %s', (mapping, expected) => {
        expect(getProducerMapping(mapping)).toEqual(expected)
    })

    it.each([
        ['*:kafkatypo', 'Invalid mapping: *:kafkatypo - target kafkatypo must be one of postgres, postgres-v2, kafka'],
        [
            'hog:kafkatypo',
            'Invalid mapping: hog:kafkatypo - target kafkatypo must be one of postgres, postgres-v2, kafka',
        ],
        [
            'hog:kafka,hogflow:postgres,*:kafkatypo',
            'Invalid mapping: *:kafkatypo - target kafkatypo must be one of postgres, postgres-v2, kafka',
        ],
        [
            'wrong_queue:kafka',
            'Invalid mapping: wrong_queue:kafka - queue wrong_queue must be one of *, hog, hogoverflow, hogflow',
        ],
        ['hog:kafka:1.1', 'Invalid mapping: hog:kafka:1.1 - percentage 1.1 must be 0 < x <= 1'],
        ['hog:kafka', 'No mapping for the default queue for example: *:postgres'],
        ['*:kafka:0.5,*:postgres:0.3', 'Invalid mapping for queue *: percentages must sum to 1 (got 0.8)'],
    ])('should throw for bad values for %s', (mapping, error) => {
        expect(() => getProducerMapping(mapping)).toThrow(error)
    })
})

describe('getProducerTeamMapping', () => {
    it('should return empty object for empty string', () => {
        expect(getProducerTeamMapping('')).toEqual({})
    })

    it('should parse a single team with a default queue', () => {
        expect(getProducerTeamMapping('1:*:postgres')).toEqual({
            '1': {
                '*': [{ target: 'postgres', percentage: 1 }],
            },
        })
    })

    it('should parse multiple teams', () => {
        expect(getProducerTeamMapping('1:*:kafka,2:*:postgres')).toEqual({
            '1': {
                '*': [{ target: 'kafka', percentage: 1 }],
            },
            '2': {
                '*': [{ target: 'postgres', percentage: 1 }],
            },
        })
    })

    it('should fill remainder from team * default', () => {
        const result = getProducerTeamMapping('79155:*:kafka,79155:hog:postgres-v2:0.001')
        expect(result['79155']['hog']).toHaveLength(2)
        expect(result['79155']['hog'][0]).toEqual({ target: 'postgres-v2', percentage: 0.001 })
        expect(result['79155']['hog'][1].target).toBe('kafka')
        expect(result['79155']['hog'][1].percentage).toBeCloseTo(0.999)
    })

    it('should fill remainder proportionally from multi-target * default', () => {
        const result = getProducerTeamMapping('79155:*:kafka:0.7,79155:*:postgres:0.3,79155:hog:postgres-v2:0.1')
        expect(result['79155']['hog']).toHaveLength(3)
        expect(result['79155']['hog'][0]).toEqual({ target: 'postgres-v2', percentage: 0.1 })
        expect(result['79155']['hog'][1].target).toBe('kafka')
        expect(result['79155']['hog'][1].percentage).toBeCloseTo(0.63)
        expect(result['79155']['hog'][2].target).toBe('postgres')
        expect(result['79155']['hog'][2].percentage).toBeCloseTo(0.27)
    })

    it('should not fill remainder when percentages already sum to 1', () => {
        const result = getProducerTeamMapping('79155:*:kafka,79155:hog:postgres-v2:0.5,79155:hog:kafka:0.5')
        expect(result['79155']['hog']).toEqual([
            { target: 'postgres-v2', percentage: 0.5 },
            { target: 'kafka', percentage: 0.5 },
        ])
    })

    it('should reject team mappings with percentages exceeding 1', () => {
        expect(() => getProducerTeamMapping('79155:*:kafka,79155:hog:postgres-v2:0.6,79155:hog:kafka:0.6')).toThrow(
            'percentages must sum to 1'
        )
    })

    it('should handle multiple teams with multiple queues', () => {
        const result = getProducerTeamMapping('1:*:kafka,1:hog:postgres:0.5,1:hog:kafka:0.5,2:*:postgres')
        expect(result['1']['*']).toEqual([{ target: 'kafka', percentage: 1 }])
        expect(result['1']['hog']).toEqual([
            { target: 'postgres', percentage: 0.5 },
            { target: 'kafka', percentage: 0.5 },
        ])
        expect(result['2']['*']).toEqual([{ target: 'postgres', percentage: 1 }])
    })

    it('should throw for malformed entries', () => {
        expect(() => getProducerTeamMapping('79155')).toThrow(
            'Invalid team mapping: 79155 - expected format TEAM:QUEUE:TARGET[:PERCENTAGE]'
        )
    })
})
