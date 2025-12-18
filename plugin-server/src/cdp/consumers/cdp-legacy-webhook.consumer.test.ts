import { mockFetch } from '../../../tests/helpers/mocks/request.mock'

import { Message } from 'node-rdkafka'

import { createOrganization, createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Action, Hook, Hub, ISOTimestamp, PostIngestionEvent, ProjectId, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresUse } from '../../utils/db/postgres'
import { FetchResponse } from '../../utils/request'
import { createHogExecutionGlobals, createIncomingEvent, createKafkaMessage } from '../_tests/fixtures'
import { HogFunctionInvocationGlobals } from '../types'
import { CdpLegacyWebhookConsumer } from './cdp-legacy-webhook.consumer'

jest.setTimeout(10000)

describe('CdpLegacyWebhookConsumer', () => {
    let processor: CdpLegacyWebhookConsumer
    let hub: Hub
    let team: Team
    let team2: Team

    const createMockAction = (teamId: number, overrides: Partial<Action> = {}): Action => {
        return {
            id: 1,
            name: 'Test Action',
            description: '',
            team_id: teamId,
            deleted: false,
            post_to_slack: false,
            slack_message_format: '',
            is_calculating: false,
            steps: [],
            hooks: [],
            created_at: new Date().toISOString(),
            created_by_id: 1,
            updated_at: new Date().toISOString(),
            last_calculated_at: new Date().toISOString(),
            ...overrides,
        }
    }

    const createMockHook = (overrides: Partial<Hook> = {}): Hook => {
        return {
            id: 'test-hook-id',
            team_id: team.id,
            user_id: 1,
            resource_id: 1,
            event: 'action_performed',
            target: 'https://hooks.zapier.com/test',
            created: new Date().toISOString(),
            updated: new Date().toISOString(),
            ...overrides,
        }
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        const otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
        team2 = (await getTeam(hub, team2Id))!

        processor = new CdpLegacyWebhookConsumer(hub)

        processor['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        await processor.start()

        mockFetch.mockResolvedValue({
            status: 200,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(''),
            dump: () => Promise.resolve(),
        } as FetchResponse)
    })

    afterEach(async () => {
        await processor.stop()
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('_parseKafkaBatch', () => {
        it('should parse events for teams with webhooks', async () => {
            hub.actionMatcher.hasWebhooks = jest.fn().mockReturnValue(true)

            const messages: Message[] = [createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' }))]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].projectId).toBe(team.id)
            expect(invocations[0].event).toBe('$pageview')
        })

        it('should filter out events for teams without webhooks', async () => {
            hub.actionMatcher.hasWebhooks = jest.fn().mockReturnValue(false)

            const messages: Message[] = [
                createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' })),
                createKafkaMessage(createIncomingEvent(team2.id, { event: '$pageview' })),
            ]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(0)
        })

        it('should filter out events for non-existent teams', async () => {
            const messages: Message[] = [createKafkaMessage(createIncomingEvent(99999, { event: '$pageview' }))]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(0)
        })

        it('should handle multiple teams correctly', async () => {
            hub.actionMatcher.hasWebhooks = jest.fn().mockImplementation((teamId) => teamId === team.id)

            const messages: Message[] = [
                createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' })),
                createKafkaMessage(createIncomingEvent(team2.id, { event: '$pageview' })),
            ]

            const invocations = await processor._parseKafkaBatch(messages)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].project.id).toBe(team.id)
        })
    })

    describe('processBatch', () => {
        let globals: HogFunctionInvocationGlobals

        beforeEach(() => {
            globals = createHogExecutionGlobals({
                project: {
                    id: team.id,
                } as any,
                event: {
                    uuid: 'test-uuid',
                    event: '$pageview',
                    distinct_id: 'test-user',
                    properties: {},
                } as any,
            })
        })

        it('should process events with webhooks', async () => {
            const action = createMockAction(team.id, { post_to_slack: true })
            hub.actionMatcher.hasWebhooks = jest.fn().mockReturnValue(true)
            hub.actionMatcher.match = jest.fn().mockReturnValue([action])
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)

            const result = await processor.processBatch([globals])

            await result.backgroundTask

            expect(result.invocations).toHaveLength(0)
            expect(hub.actionMatcher.match).toHaveBeenCalled()
        })

        it('should skip events without webhooks', async () => {
            hub.actionMatcher.hasWebhooks = jest.fn().mockReturnValue(false)
            const matchSpy = jest.spyOn(hub.actionMatcher, 'match')

            const result = await processor.processBatch([globals])

            await result.backgroundTask

            expect(result.invocations).toHaveLength(0)
            expect(matchSpy).not.toHaveBeenCalled()
        })

        it('should enrich events with group properties when group analytics is enabled', async () => {
            const action = createMockAction(team.id, { post_to_slack: true })
            hub.actionMatcher.hasWebhooks = jest.fn().mockReturnValue(true)
            hub.actionMatcher.match = jest.fn().mockReturnValue([action])
            hub.teamManager.hasAvailableFeature = jest.fn().mockImplementation((teamId, feature) => {
                return feature === 'group_analytics' || feature === 'zapier'
            })
            hub.groupTypeManager.fetchGroupTypes = jest.fn().mockResolvedValue({
                project: 0,
            })
            hub.groupRepository.fetchGroup = jest.fn().mockResolvedValue({
                group_properties: { name: 'Test Project' },
            })

            globals.event.properties['$groups'] = { project: 'test-project-id' }

            const result = await processor.processBatch([globals])

            await result.backgroundTask

            expect(hub.groupTypeManager.fetchGroupTypes).toHaveBeenCalled()
            expect(hub.groupRepository.fetchGroup).toHaveBeenCalledWith(team.id, 0, 'test-project-id', {
                useReadReplica: true,
            })
        })
    })

    describe('fireWebhooks', () => {
        let event: PostIngestionEvent

        beforeEach(() => {
            event = {
                eventUuid: 'test-uuid',
                event: '$pageview',
                teamId: team.id,
                distinctId: 'test-user',
                properties: {},
                timestamp: new Date().toISOString() as ISOTimestamp,
                projectId: team.id as ProjectId,
                person_created_at: null,
                person_properties: {},
                person_id: undefined,
            }
        })

        it('should fire Zapier webhooks when zapier feature is enabled', async () => {
            const hook = createMockHook()
            const action = createMockAction(team.id, { hooks: [hook] })

            hub.actionMatcher.match = jest.fn().mockReturnValue([action])
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)

            await processor['fireWebhooks'](event, [action])

            expect(mockFetch).toHaveBeenCalledWith(
                'https://hooks.zapier.com/test',
                expect.objectContaining({
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                })
            )
        })

        it('should not fire Zapier webhooks when zapier feature is disabled', async () => {
            const hook = createMockHook()
            const action = createMockAction(team.id, { hooks: [hook] })

            hub.actionMatcher.match = jest.fn().mockReturnValue([action])
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)

            await processor['fireWebhooks'](event, [action])

            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('should handle multiple actions with webhooks', async () => {
            const action1 = createMockAction(team.id, {
                id: 1,
                post_to_slack: false,
                hooks: [createMockHook({ id: 'hook-1' })],
            })
            const action2 = createMockAction(team.id, {
                id: 2,
                post_to_slack: false,
                hooks: [createMockHook({ id: 'hook-2', target: 'https://hooks.zapier.com/test2' })],
            })

            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)

            await processor['fireWebhooks'](event, [action1, action2])

            expect(mockFetch).toHaveBeenCalledTimes(2)
        })
    })

    describe('postWebhook', () => {
        let event: PostIngestionEvent
        let action: Action

        beforeEach(() => {
            event = {
                eventUuid: 'test-uuid',
                event: '$pageview',
                teamId: team.id,
                distinctId: 'test-user',
                properties: {},
                timestamp: new Date().toISOString() as ISOTimestamp,
                projectId: team.id as ProjectId,
                person_created_at: null,
                person_properties: {},
                person_id: undefined,
            }

            action = createMockAction(team.id)
        })

        it('should send webhook request', async () => {
            const hook = createMockHook()

            await processor['postWebhook'](event, action, team, hook)

            expect(mockFetch).toHaveBeenCalledWith(
                'https://hooks.zapier.com/test',
                expect.objectContaining({
                    method: 'POST',
                })
            )
        })

        it('should delete hook on 410 response', async () => {
            const hook = createMockHook()
            mockFetch.mockResolvedValue({
                status: 410,
                headers: {},
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(''),
                dump: () => Promise.resolve(),
            } as FetchResponse)

            const querySpy = jest.spyOn(hub.postgres, 'query')

            await processor['postWebhook'](event, action, team, hook)

            expect(querySpy).toHaveBeenCalledWith(
                PostgresUse.COMMON_WRITE,
                expect.stringContaining('DELETE FROM ee_hook'),
                ['test-hook-id'],
                'deleteRestHook'
            )
        })

        it('should skip when no URL is provided', async () => {
            const hook = createMockHook({ target: '' })

            await processor['postWebhook'](event, action, team, hook)

            expect(mockFetch).not.toHaveBeenCalled()
        })
    })

    describe('addGroupPropertiesToEvent', () => {
        let globals: HogFunctionInvocationGlobals

        beforeEach(() => {
            globals = createHogExecutionGlobals({
                project: {
                    id: team.id,
                } as any,
                event: {
                    uuid: 'test-uuid',
                    event: '$pageview',
                    distinct_id: 'test-user',
                    properties: {},
                } as any,
            })
        })

        it('should add group properties when group analytics is enabled', async () => {
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            hub.groupTypeManager.fetchGroupTypes = jest.fn().mockResolvedValue({
                project: 0,
            })
            hub.groupRepository.fetchGroup = jest.fn().mockResolvedValue({
                group_properties: { name: 'Test Project' },
            })

            globals.event.properties['$groups'] = { project: 'test-project-id' }

            const result = await processor['addGroupPropertiesToEvent'](globals)

            expect(result.groups).toBeDefined()
            expect(result.groups?.project).toEqual({
                index: 0,
                key: 'test-project-id',
                type: 'project',
                properties: { name: 'Test Project' },
            })
        })

        it('should not add group properties when group analytics is disabled', async () => {
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)
            const fetchGroupTypesSpy = jest.spyOn(hub.groupTypeManager, 'fetchGroupTypes')

            const result = await processor['addGroupPropertiesToEvent'](globals)

            expect(result.groups).toBeUndefined()
            expect(fetchGroupTypesSpy).not.toHaveBeenCalled()
        })

        it('should handle missing group keys', async () => {
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            hub.groupTypeManager.fetchGroupTypes = jest.fn().mockResolvedValue({
                project: 0,
                organization: 1,
            })

            globals.event.properties['$groups'] = { project: 'test-project-id' }

            const result = await processor['addGroupPropertiesToEvent'](globals)

            expect(result.groups).toBeDefined()
            expect(result.groups?.project).toBeDefined()
            expect(result.groups?.organization).toBeUndefined()
        })

        it('should handle null group properties', async () => {
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            hub.groupTypeManager.fetchGroupTypes = jest.fn().mockResolvedValue({
                project: 0,
            })
            hub.groupRepository.fetchGroup = jest.fn().mockResolvedValue(null)

            globals.event.properties['$groups'] = { project: 'test-project-id' }

            const result = await processor['addGroupPropertiesToEvent'](globals)

            // When group is null, groupProperties becomes {}, which is still added
            expect(result.groups).toBeDefined()
            expect(result.groups?.project).toEqual({
                index: 0,
                key: 'test-project-id',
                type: 'project',
                properties: {},
            })
        })
    })
})
