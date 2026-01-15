import { HogFlow } from '~/schema/hogflow'
import { UUIDT } from '~/utils/utils'

import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createKafkaMessage } from '../_tests/fixtures'
import { insertHogFlow as _insertHogFlow } from '../_tests/fixtures-hogflows'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { BatchHogFlowRequest, CdpBatchHogFlowRequestsConsumer } from './cdp-batch-hogflow.consumer'

jest.setTimeout(1000)

describe('CdpBatchHogFlowRequestsConsumer', () => {
    let processor: CdpBatchHogFlowRequestsConsumer
    let hub: Hub
    let team: Team
    let mockQueueInvocations: jest.Mock

    const insertHogFlow = async (hogFlow: HogFlow) => {
        const teamId = hogFlow.team_id ?? team.id
        const item = await _insertHogFlow(hub.postgres, {
            ...hogFlow,
            team_id: teamId,
        })
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        processor = new CdpBatchHogFlowRequestsConsumer(hub)

        // NOTE: We don't want to actually connect to Kafka for these tests as it is slow and we are testing the core logic only
        processor['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        processor['cyclotronJobQueue'] = {
            queueInvocations: jest.fn(),
            startAsProducer: jest.fn(() => Promise.resolve()),
            stop: jest.fn(),
        } as unknown as jest.Mocked<CyclotronJobQueue>

        mockQueueInvocations = jest.mocked(processor['cyclotronJobQueue']['queueInvocations'])

        await processor.start()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('_parseKafkaBatch', () => {
        it('should parse valid batch hog flow request messages', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                    filter_test_accounts: false,
                },
            }

            const messages = [createKafkaMessage(batchRequest)]

            const result = await processor._parseKafkaBatch(messages)

            expect(result).toHaveLength(1)
            expect(result[0]).toMatchObject({
                batchHogFlowRequest: batchRequest,
                team: expect.objectContaining({ id: team.id }),
                hogFlow: expect.objectContaining({ id: hogFlow.id }),
            })
        })

        it('should filter out messages with missing hog flows', async () => {
            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: 'non-existent-id',
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const messages = [createKafkaMessage(batchRequest)]

            const result = await processor._parseKafkaBatch(messages)

            expect(result).toHaveLength(0)
        })

        it('should filter out messages with missing teams', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            const batchRequest: BatchHogFlowRequest = {
                teamId: 999999, // Non-existent team
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const messages = [createKafkaMessage(batchRequest)]

            const result = await processor._parseKafkaBatch(messages)

            expect(result).toHaveLength(0)
        })

        it('should handle malformed messages gracefully', async () => {
            const messages = [
                {
                    partition: 1,
                    topic: 'test',
                    offset: 0,
                    timestamp: Date.now(),
                    size: 1,
                    value: Buffer.from('invalid json'),
                },
            ]

            const result = await processor._parseKafkaBatch(messages as any)

            expect(result).toHaveLength(0)
        })

        it('should filter out messages with draft hogflow status', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .withStatus('draft')
                    .build()
            )

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const messages = [createKafkaMessage(batchRequest)]

            const result = await processor._parseKafkaBatch(messages)

            expect(result).toHaveLength(0)
        })

        it('should filter out messages with archived hogflow status', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .withStatus('archived')
                    .build()
            )

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const messages = [createKafkaMessage(batchRequest)]

            const result = await processor._parseKafkaBatch(messages)

            expect(result).toHaveLength(0)
        })
    })

    describe('createHogFlowInvocations', () => {
        it('should return empty array if filters.properties is missing', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: {} as any,
                        },
                    })
                    .build()
            )

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {},
            }

            const result = await processor['createHogFlowInvocations']({
                batchHogFlowRequest: batchRequest,
                team,
                hogFlow,
            })

            expect(result).toHaveLength(0)
        })

        it('should create invocations for matching persons', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            // Mock the personsManager to return some persons
            const mockCountMany = jest.fn().mockResolvedValue(2)
            const mockStreamMany = jest.fn().mockImplementation(async ({ onPersonBatch }: any) => {
                await onPersonBatch([
                    { personId: 'person-1', distinctId: 'distinct-1' },
                    { personId: 'person-2', distinctId: 'distinct-2' },
                ])
            })

            processor['personsManager'].countMany = mockCountMany
            processor['personsManager'].streamMany = mockStreamMany

            // Mock rate limiter to not limit
            jest.spyOn(processor['hogRateLimiter'], 'rateLimitMany').mockResolvedValue([
                [hogFlow.id, { isRateLimited: false, tokens: 100 }],
            ])

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const result = await processor['createHogFlowInvocations']({
                batchHogFlowRequest: batchRequest,
                team,
                hogFlow,
            })

            expect(result).toHaveLength(2)
            expect(result[0]).toMatchObject({
                id: expect.any(String),
                teamId: team.id,
                functionId: hogFlow.id,
                parentRunId: batchRequest.parentRunId,
                queue: 'hogflow',
                queuePriority: 1,
                state: {
                    event: expect.objectContaining({
                        event: '$batch_hog_flow_invocation',
                        distinct_id: 'distinct-1',
                    }),
                    actionStepCount: 0,
                },
                person: expect.objectContaining({
                    id: 'person-1',
                }),
            })
            expect(result[1]).toMatchObject({
                id: expect.any(String),
                teamId: team.id,
                parentRunId: batchRequest.parentRunId,
                functionId: hogFlow.id,
                queue: 'hogflow',
                queuePriority: 1,
                state: {
                    event: expect.objectContaining({
                        event: '$batch_hog_flow_invocation',
                        distinct_id: 'distinct-2',
                    }),
                    actionStepCount: 0,
                },
                person: expect.objectContaining({
                    id: 'person-2',
                }),
            })

            expect(mockCountMany).toHaveBeenCalledWith({
                teamId: team.id,
                properties: batchRequest.filters.properties,
            })
            expect(mockStreamMany).toHaveBeenCalledWith({
                filters: {
                    teamId: team.id,
                    properties: batchRequest.filters.properties,
                },
                onPersonBatch: expect.any(Function),
            })
        })

        it('should include default variables from hogFlow', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            // Add variables to hogFlow
            hogFlow.variables = [
                { key: 'customVar1', type: 'string', label: 'Custom Var 1', default: 'defaultValue1' },
                { key: 'customVar2', type: 'number', label: 'Custom Var 2', default: 42 },
                { key: 'customVar3', type: 'string', label: 'Custom Var 3' }, // No default
            ]

            // Mock the personsManager
            const mockStreamMany = jest.fn().mockImplementation(async ({ onPersonBatch }: any) => {
                await onPersonBatch([{ personId: 'person-1', distinctId: 'distinct-1' }])
            })
            jest.spyOn(processor['personsManager'], 'countMany').mockResolvedValue(1)
            processor['personsManager'].streamMany = mockStreamMany

            // Mock rate limiter
            jest.spyOn(processor['hogRateLimiter'], 'rateLimitMany').mockResolvedValue([
                [hogFlow.id, { isRateLimited: false, tokens: 100 }],
            ])

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const result = await processor['createHogFlowInvocations']({
                batchHogFlowRequest: batchRequest,
                team,
                hogFlow,
            })

            expect(result).toHaveLength(1)
            expect(result[0].state?.variables).toEqual({
                customVar1: 'defaultValue1',
                customVar2: 42,
                customVar3: null,
            })
        })
    })

    describe('processBatch', () => {
        it('should process batch and queue invocations', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            // Mock the personsManager
            const mockStreamMany = jest.fn().mockImplementation(async ({ onPersonBatch }: any) => {
                await onPersonBatch([{ personId: 'person-1', distinctId: 'distinct-1' }])
            })
            jest.spyOn(processor['personsManager'], 'countMany').mockResolvedValue(1)
            processor['personsManager'].streamMany = mockStreamMany

            // Mock rate limiter
            jest.spyOn(processor['hogRateLimiter'], 'rateLimitMany').mockResolvedValue([
                [hogFlow.id, { isRateLimited: false, tokens: 100 }],
            ])

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const batchHogFlowRequestMessages = [
                {
                    batchHogFlowRequest: batchRequest,
                    team,
                    hogFlow,
                },
            ]

            const { invocations, backgroundTask } = await processor['processBatch'](batchHogFlowRequestMessages)

            expect(invocations).toHaveLength(1)
            expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)

            // Wait for background task to complete
            await backgroundTask
        })

        it('should handle empty batch', async () => {
            const { invocations, backgroundTask } = await processor['processBatch']([])

            expect(invocations).toHaveLength(0)
            expect(mockQueueInvocations).not.toHaveBeenCalled()

            await backgroundTask
        })

        it('should process multiple requests in batch', async () => {
            const hogFlow1 = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            const hogFlow2 = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            // Mock the personsManager
            const mockStreamMany = jest.fn().mockImplementation(async ({ onPersonBatch }: any) => {
                await onPersonBatch([{ personId: 'person-1', distinctId: 'distinct-1' }])
            })
            jest.spyOn(processor['personsManager'], 'countMany').mockResolvedValue(1)
            processor['personsManager'].streamMany = mockStreamMany

            // Mock rate limiter
            jest.spyOn(processor['hogRateLimiter'], 'rateLimitMany').mockResolvedValue([
                [hogFlow1.id, { isRateLimited: false, tokens: 100 }],
                [hogFlow2.id, { isRateLimited: false, tokens: 100 }],
            ])

            const batchRequest1: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow1.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test1@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const batchRequest2: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow2.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test2@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const batchHogFlowRequestMessages = [
                { batchHogFlowRequest: batchRequest1, team, hogFlow: hogFlow1 },
                { batchHogFlowRequest: batchRequest2, team, hogFlow: hogFlow2 },
            ]

            const { invocations, backgroundTask } = await processor['processBatch'](batchHogFlowRequestMessages)

            expect(invocations).toHaveLength(2)
            expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
            expect(invocations[0].functionId).toBe(hogFlow1.id)
            expect(invocations[1].functionId).toBe(hogFlow2.id)

            await backgroundTask
        })
    })

    describe('integration', () => {
        it('should process end-to-end from kafka messages to queued invocations', async () => {
            const hogFlow = await insertHogFlow(
                new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'batch',
                            filters: { properties: [] },
                        },
                    })
                    .build()
            )

            // Mock the personsManager
            const mockStreamMany = jest.fn().mockImplementation(async ({ onPersonBatch }: any) => {
                await onPersonBatch([
                    { personId: 'person-1', distinctId: 'distinct-1' },
                    { personId: 'person-2', distinctId: 'distinct-2' },
                ])
            })
            jest.spyOn(processor['personsManager'], 'countMany').mockResolvedValue(2)
            processor['personsManager'].streamMany = mockStreamMany

            // Mock rate limiter
            jest.spyOn(processor['hogRateLimiter'], 'rateLimitMany').mockResolvedValue([
                [hogFlow.id, { isRateLimited: false, tokens: 100 }],
            ])

            const batchRequest: BatchHogFlowRequest = {
                teamId: team.id,
                hogFlowId: hogFlow.id,
                parentRunId: new UUIDT().toString(),
                filters: {
                    properties: [{ key: 'email', value: 'test@example.com', operator: 'exact', type: 'person' }],
                },
            }

            const messages = [createKafkaMessage(batchRequest)]

            // Parse Kafka messages
            const parsedMessages = await processor._parseKafkaBatch(messages)
            expect(parsedMessages).toHaveLength(1)

            // Process the batch
            const { invocations, backgroundTask } = await processor['processBatch'](parsedMessages)

            expect(invocations).toHaveLength(2)
            expect(invocations[0]).toMatchObject({
                teamId: team.id,
                functionId: hogFlow.id,
                queue: 'hogflow',
                state: {
                    event: expect.objectContaining({
                        distinct_id: 'distinct-1',
                    }),
                },
            })
            expect(invocations[1]).toMatchObject({
                teamId: team.id,
                functionId: hogFlow.id,
                queue: 'hogflow',
                state: {
                    event: expect.objectContaining({
                        distinct_id: 'distinct-2',
                    }),
                },
            })

            expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)

            await backgroundTask
        })
    })
})
