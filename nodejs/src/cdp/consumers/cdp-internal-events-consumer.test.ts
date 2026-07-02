import { createMockJobQueue } from '../../../tests/helpers/mocks/job-queue.mock'
import '../../../tests/helpers/mocks/producer.mock'

import { closeHub, createHub } from '~/common/utils/db/hub'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { createOrganization, createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { insertHogFunction as _insertHogFunction, createInternalEvent, createKafkaMessage } from '../_tests/fixtures'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { HogFunctionType } from '../types'
import { CdpInternalEventsConsumer } from './cdp-internal-event.consumer'

describe('CDP Internal Events Consumer', () => {
    let processor: CdpInternalEventsConsumer
    let hub: Hub
    let team: Team
    let team2: Team
    let mockQueueInvocations: jest.MockedFunction<any>

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const teamId = hogFunction.team_id ?? team.id
        const item = await _insertHogFunction(hub.postgres, teamId, {
            ...hogFunction,
            type: 'internal_destination',
        })
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](teamId, [item.id])
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        team = await getFirstTeam(hub.postgres)

        const otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
        team2 = (await getTeam(hub.postgres, team2Id))!

        jest.spyOn(hub.quotaLimiting, 'isTeamQuotaLimited').mockResolvedValue(false)

        const mockJobQueue = createMockJobQueue()
        processor = new CdpInternalEventsConsumer(hub, createCdpConsumerDeps(hub), mockJobQueue)

        // Don't actually connect Kafka — test the core logic only
        processor['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        mockQueueInvocations = mockJobQueue.queueInvocations

        await processor.start()
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('_parseKafkaBatch', () => {
        it('should ignore invalid message', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage({})])
            expect(events).toHaveLength(0)
        })

        it('should ignore message with no team', async () => {
            const events = await processor._parseKafkaBatch([createKafkaMessage(createInternalEvent(999999, {}))])
            expect(events).toHaveLength(0)
        })

        describe('with an existing team and hog function', () => {
            beforeEach(async () => {
                await insertHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                })
            })

            it('should ignore invalid payloads', async () => {
                const events = await processor._parseKafkaBatch([
                    createKafkaMessage(
                        createInternalEvent(team.id, {
                            event: 'WRONG' as any,
                        })
                    ),
                ])
                expect(events).toHaveLength(0)
            })

            it('should parse a valid message with an existing team and hog function ', async () => {
                const event = createInternalEvent(team.id, {})
                event.event.timestamp = '2024-12-18T15:06:23.545Z'
                event.event.uuid = 'b6da2f33-ba54-4550-9773-50d3278ad61f'

                const events = await processor._parseKafkaBatch([createKafkaMessage(event)])
                expect(events).toHaveLength(1)
                expect(events[0]).toEqual({
                    event: {
                        distinct_id: 'distinct_id',
                        elements_chain: '',
                        event: '$pageview',
                        captured_at: null,
                        properties: {},
                        timestamp: '2024-12-18T15:06:23.545Z',
                        url: '',
                        uuid: 'b6da2f33-ba54-4550-9773-50d3278ad61f',
                    },
                    person: undefined,
                    project: {
                        id: 2,
                        name: 'TEST PROJECT',
                        url: 'http://localhost:8000/project/2',
                    },
                })
            })
        })
    })

    describe('team filtering', () => {
        it('should not parse events for teams without hog functions', async () => {
            await insertHogFunction({
                team_id: team.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const events = [
                createKafkaMessage(createInternalEvent(team.id, {})),
                createKafkaMessage(createInternalEvent(team2.id, {})),
            ]

            const invocations = await processor._parseKafkaBatch(events)
            expect(invocations).toHaveLength(1)
            expect(invocations[0].project.id).toBe(team.id)

            await insertHogFunction({
                team_id: team2.id,
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const invocations2 = await processor._parseKafkaBatch(events)
            expect(invocations2).toHaveLength(2)
        })
    })

    describe('processBatch', () => {
        it('should build invocations from internal events and queue them', async () => {
            const fn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const messages = [createKafkaMessage(createInternalEvent(team.id, {}))]
            const globals = await processor._parseKafkaBatch(messages)
            const { invocations, backgroundTask } = await processor.processBatch(globals)
            await backgroundTask

            expect(invocations).toHaveLength(1)
            expect(invocations[0].functionId).toBe(fn.id)
            expect(mockQueueInvocations).toHaveBeenCalledWith(invocations)
        })

        it('should return empty when given no events', async () => {
            const { invocations, backgroundTask } = await processor.processBatch([])
            await backgroundTask

            expect(invocations).toHaveLength(0)
            expect(mockQueueInvocations).not.toHaveBeenCalled()
        })

        it('should filter out functions that are disabled', async () => {
            const fn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
            await processor.hogWatcher.forceStateChange(fn, HogWatcherState.disabled)

            const messages = [createKafkaMessage(createInternalEvent(team.id, {}))]
            const globals = await processor._parseKafkaBatch(messages)
            const { invocations } = await processor.processBatch(globals)

            expect(invocations).toHaveLength(0)
        })

        it('should only load internal_destination hog functions (filters out destination type)', async () => {
            // Insert a `destination` type function for the same team
            await _insertHogFunction(hub.postgres, team.id, {
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                type: 'destination',
            })

            // Insert an internal_destination function — should be the only one picked up
            const internalFn = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const messages = [createKafkaMessage(createInternalEvent(team.id, {}))]
            const globals = await processor._parseKafkaBatch(messages)
            const { invocations } = await processor.processBatch(globals)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].functionId).toBe(internalFn.id)
        })
    })
})
