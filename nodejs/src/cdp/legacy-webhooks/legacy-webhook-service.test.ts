import { mockFetch } from '../../../tests/helpers/mocks/request.mock'

import { Message } from 'node-rdkafka'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'

import { createOrganization, createTeam, getFirstTeam, getTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Action, ClickHouseTimestamp, Hook, Hub, ISOTimestamp, PostIngestionEvent, ProjectId, Team } from '../../types'
import { createIncomingEvent, createKafkaMessage } from '../_tests/fixtures'
import { LegacyWebhookService } from './legacy-webhook-service'

jest.setTimeout(10000)

describe('LegacyWebhookService', () => {
    let service: LegacyWebhookService
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

    const createMockHook = (teamId: number, overrides: Partial<Hook> = {}): Hook => {
        return {
            id: 'test-hook-id',
            team_id: teamId,
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
        team = await getFirstTeam(hub.postgres)
        const otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
        team2 = (await getTeam(hub.postgres, team2Id))!

        service = new LegacyWebhookService(hub.postgres, hub.teamManager, hub.pubSub)
        await service.start()

        mockFetch.mockResolvedValue({
            status: 200,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(''),
            dump: () => Promise.resolve(),
        } as FetchResponse)
    })

    afterEach(async () => {
        await service.stop()
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('processBatch', () => {
        it('should parse events for teams with both webhooks and zapier', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockReturnValue(true)
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)

            const messages: Message[] = [createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' }))]

            const result = await service.processBatch(messages)
            await result.backgroundTask

            expect(service['actionMatcher'].hasWebhooks).toHaveBeenCalledWith(team.id)
        })

        it('should filter out events for teams without webhooks and without zapier', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockReturnValue(false)
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)
            service.processEvent = jest.fn()

            const messages: Message[] = [
                createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' })),
                createKafkaMessage(createIncomingEvent(team2.id, { event: '$pageview' })),
            ]

            const result = await service.processBatch(messages)
            await result.backgroundTask

            expect(service.processEvent).not.toHaveBeenCalled()
        })

        it('should filter out events for teams with zapier but without webhooks', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockReturnValue(false)
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            service.processEvent = jest.fn()

            const messages: Message[] = [createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' }))]

            const result = await service.processBatch(messages)
            await result.backgroundTask

            expect(service.processEvent).not.toHaveBeenCalled()
        })

        it('should filter out events for teams with webhooks but without zapier', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockReturnValue(true)
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)
            service.processEvent = jest.fn()

            const messages: Message[] = [createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' }))]

            const result = await service.processBatch(messages)
            await result.backgroundTask

            expect(service.processEvent).not.toHaveBeenCalled()
        })

        it('should handle multiple teams correctly', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockImplementation((teamId) => teamId === team.id)
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            service.processEvent = jest.fn()

            const messages: Message[] = [
                createKafkaMessage(createIncomingEvent(team.id, { event: '$pageview' })),
                createKafkaMessage(createIncomingEvent(team2.id, { event: '$pageview' })),
            ]

            const result = await service.processBatch(messages)
            await result.backgroundTask

            expect(service.processEvent).toHaveBeenCalledTimes(1)
        })

        it('should not query the group repository when processing events with $groups', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockReturnValue(true)
            // Both zapier and group_analytics enabled — group_analytics used to trigger enrichment
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            const fetchGroupsByKeysSpy = jest.spyOn(hub.groupRepository, 'fetchGroupsByKeys')
            const fetchGroupSpy = jest.spyOn(hub.groupRepository, 'fetchGroup')
            service.processEvent = jest.fn()

            const messages: Message[] = [
                createKafkaMessage(
                    createIncomingEvent(team.id, {
                        event: '$pageview',
                        properties: JSON.stringify({ $groups: { project: 'test-project-id' } }),
                    })
                ),
            ]

            const result = await service.processBatch(messages)
            await result.backgroundTask

            expect(fetchGroupsByKeysSpy).not.toHaveBeenCalled()
            expect(fetchGroupSpy).not.toHaveBeenCalled()
        })

        it('posts an identical payload regardless of group_analytics and never adds a groups key', async () => {
            service['actionMatcher'].hasWebhooks = jest.fn().mockReturnValue(true)
            const hook = createMockHook(team.id)
            const action = createMockAction(team.id, { hooks: [hook] })
            service['actionMatcher'].match = jest.fn().mockReturnValue([action])

            const fetchGroupsByKeysSpy = jest.spyOn(hub.groupRepository, 'fetchGroupsByKeys')
            const fetchGroupSpy = jest.spyOn(hub.groupRepository, 'fetchGroup')

            // Pin volatile fields so the two events are byte-for-byte identical
            const fixedTimestamp = '2024-01-01 00:00:00.000' as ClickHouseTimestamp
            const makeMessage = (): Message =>
                createKafkaMessage(
                    createIncomingEvent(team.id, {
                        uuid: 'fixed-event-uuid',
                        event: '$pageview',
                        properties: JSON.stringify({ $groups: { project: 'test-project-id' }, foo: 'bar' }),
                        timestamp: fixedTimestamp,
                        created_at: fixedTimestamp,
                        person_created_at: fixedTimestamp,
                    })
                )

            // group_analytics ON (and zapier ON)
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)
            let result = await service.processBatch([makeMessage()])
            await result.backgroundTask
            const bodyWithGroupAnalytics = parseJSON(mockFetch.mock.calls[0][1].body)

            mockFetch.mockClear()

            // group_analytics OFF (zapier still ON) — the non-group case
            hub.teamManager.hasAvailableFeature = jest
                .fn()
                .mockImplementation((_teamId, feature) => Promise.resolve(feature === 'zapier'))
            result = await service.processBatch([makeMessage()])
            await result.backgroundTask
            const bodyWithoutGroupAnalytics = parseJSON(mockFetch.mock.calls[0][1].body)

            // The payload is byte-for-byte identical whether or not group_analytics is enabled
            expect(bodyWithGroupAnalytics).toEqual(bodyWithoutGroupAnalytics)
            // ...and crucially never carries a top-level groups key
            expect(bodyWithGroupAnalytics.data).not.toHaveProperty('groups')
            // ...while the fields that consumers actually read remain intact
            expect(bodyWithGroupAnalytics.data.properties).toMatchObject({
                $groups: { project: 'test-project-id' },
                foo: 'bar',
            })
            expect(bodyWithGroupAnalytics.data).toHaveProperty('person')
            expect(bodyWithGroupAnalytics.data).toHaveProperty('elementsList')
            // ...and we never reach into the group repository
            expect(fetchGroupsByKeysSpy).not.toHaveBeenCalled()
            expect(fetchGroupSpy).not.toHaveBeenCalled()
        })
    })

    describe('processEvent', () => {
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

        it('should process events with matching actions', async () => {
            const hook = createMockHook(team.id)
            const action = createMockAction(team.id, { hooks: [hook] })
            service['actionMatcher'].match = jest.fn().mockReturnValue([action])
            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)

            await service.processEvent(event)

            expect(service['actionMatcher'].match).toHaveBeenCalledWith(event)
            expect(mockFetch).toHaveBeenCalledWith(
                'https://hooks.zapier.com/test',
                expect.objectContaining({
                    method: 'POST',
                })
            )
        })

        it('should skip events without matching actions', async () => {
            service['actionMatcher'].match = jest.fn().mockReturnValue([])

            await service.processEvent(event)

            expect(service['actionMatcher'].match).toHaveBeenCalledWith(event)
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('should skip events when team not found', async () => {
            const hook = createMockHook(team.id)
            const action = createMockAction(team.id, { hooks: [hook] })
            service['actionMatcher'].match = jest.fn().mockReturnValue([action])
            hub.teamManager.getTeam = jest.fn().mockResolvedValue(null)

            await service.processEvent(event)

            expect(mockFetch).not.toHaveBeenCalled()
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

        it('should fire webhooks when zapier feature is enabled', async () => {
            const hook = createMockHook(team.id)
            const action = createMockAction(team.id, { hooks: [hook] })

            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)

            await service['fireWebhooks'](event, [action])

            expect(mockFetch).toHaveBeenCalledWith(
                'https://hooks.zapier.com/test',
                expect.objectContaining({
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                })
            )
        })

        it('should not fire webhooks when zapier feature is disabled', async () => {
            const hook = createMockHook(team.id)
            const action = createMockAction(team.id, { hooks: [hook] })

            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)

            await service['fireWebhooks'](event, [action])

            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('should handle multiple actions with webhooks', async () => {
            const action1 = createMockAction(team.id, {
                id: 1,
                hooks: [createMockHook(team.id, { id: 'hook-1' })],
            })
            const action2 = createMockAction(team.id, {
                id: 2,
                hooks: [createMockHook(team.id, { id: 'hook-2', target: 'https://hooks.zapier.com/test2' })],
            })

            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(true)

            await service['fireWebhooks'](event, [action1, action2])

            expect(mockFetch).toHaveBeenCalledTimes(2)
        })
    })

    describe('postWebhook', () => {
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

        it('should send webhook request', async () => {
            const hook = createMockHook(team.id)

            await service['postWebhook'](event, team, hook)

            expect(mockFetch).toHaveBeenCalledWith(
                'https://hooks.zapier.com/test',
                expect.objectContaining({
                    method: 'POST',
                })
            )
        })

        it('should delete hook on 410 response', async () => {
            const hook = createMockHook(team.id)
            mockFetch.mockResolvedValue({
                status: 410,
                headers: {},
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(''),
                dump: () => Promise.resolve(),
            } as FetchResponse)

            const querySpy = jest.spyOn(hub.postgres, 'query')

            await service['postWebhook'](event, team, hook)

            expect(querySpy).toHaveBeenCalledWith(
                PostgresUse.COMMON_WRITE,
                expect.stringContaining('DELETE FROM ee_hook'),
                ['test-hook-id'],
                'deleteRestHook'
            )
        })

        it('should skip when no URL is provided', async () => {
            const hook = createMockHook(team.id, { target: '' })

            await service['postWebhook'](event, team, hook)

            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('should throw error when fetch has an error', async () => {
            const hook = createMockHook(team.id)
            mockFetch.mockRejectedValue(new Error('Network error'))

            await expect(service['postWebhook'](event, team, hook)).rejects.toThrow('Network error')
        })
    })
})
