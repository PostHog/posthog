import { mockFetch } from '../../../tests/helpers/mocks/request.mock'

import { Message } from 'node-rdkafka'
import { randomUUID } from 'node:crypto'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'

import {
    createAction,
    createOrganization,
    createTeam,
    createTestTeamFixture,
    getTeam,
    insertRow,
    updateOrganizationAvailableFeatures,
} from '../../../tests/helpers/sql'
import { Action, ClickHouseTimestamp, Hook, Hub, ISOTimestamp, PostIngestionEvent, ProjectId, Team } from '../../types'
import { createIncomingEvent, createKafkaMessage } from '../_tests/fixtures'
import { LegacyWebhookService } from './legacy-webhook-service'

jest.setTimeout(10000)

describe('LegacyWebhookService', () => {
    let service: LegacyWebhookService
    let hub: Hub
    let team: Team
    let team2: Team
    let organizationId: string
    let otherOrganizationId: string
    let userId: number
    let stopService: (() => Promise<void>) | undefined

    const ZAPIER = { key: 'zapier', name: 'Zapier' }

    const fetchResponse = (status: number): FetchResponse =>
        ({
            status,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(''),
            dump: () => Promise.resolve(),
        }) as FetchResponse

    const createPageviewHook = async (teamId: number, target: string): Promise<string> => {
        const actionId = await createAction(hub.postgres, teamId, 'Pageview', null, {
            steps_json: [
                {
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: '$pageview',
                    properties: [],
                },
            ],
        })
        const hookId = randomUUID()
        await insertRow(hub.postgres, 'ee_hook', {
            id: hookId,
            team_id: teamId,
            user_id: userId,
            resource_id: actionId,
            event: 'action_performed',
            target,
            created: new Date().toISOString(),
            updated: new Date().toISOString(),
        })
        return hookId
    }

    const storedHookIds = async (hookIds: string[]): Promise<string[]> => {
        const { rows } = await hub.postgres.query<{ id: string }>(
            PostgresUse.COMMON_READ,
            'SELECT id FROM ee_hook WHERE id = ANY($1)',
            [hookIds],
            'readTestHooks'
        )
        return rows.map(({ id }) => id).sort()
    }

    const pageview = (teamId: number): Message =>
        createKafkaMessage(createIncomingEvent(teamId, { event: '$pageview' }))

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

    const parseAndSend = async (messages: Message[]) => {
        const events = await service.parseBatch(messages)
        await service.processEvents(events).backgroundTask
        const requests = mockFetch.mock.calls.map(([url, init]) => ({
            url,
            method: init?.method,
            headers: init?.headers,
            body: parseJSON(init?.body as string),
        }))
        return { events, requests }
    }

    const startService = async (): Promise<void> => {
        const started = new LegacyWebhookService(hub.postgres, hub.teamManager, hub.pubSub)
        await started.start()
        service = started
        stopService = () => started.stop()
    }

    beforeEach(async () => {
        hub = await createHub()
        const fixture = await createTestTeamFixture(hub.postgres)
        team = fixture.team
        organizationId = fixture.organizationId
        userId = fixture.userId
        otherOrganizationId = await createOrganization(hub.postgres)
        const team2Id = await createTeam(hub.postgres, otherOrganizationId)
        team2 = (await getTeam(hub.postgres, team2Id))!

        mockFetch.mockResolvedValue(fetchResponse(200))
    })

    afterEach(async () => {
        await stopService?.()
        stopService = undefined
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('parseBatch and processEvents', () => {
        it.each([
            { teamHas: 'zapier but no webhook', features: [ZAPIER], targets: [] },
            { teamHas: 'a webhook but no zapier', features: [], targets: ['https://hooks.zapier.com/team'] },
        ])('drops the events of a team with $teamHas', async ({ features, targets }) => {
            await updateOrganizationAvailableFeatures(hub.postgres, organizationId, features)
            await Promise.all(targets.map((target) => createPageviewHook(team.id, target)))
            await startService()

            const { events, requests } = await parseAndSend([pageview(team.id)])

            expect(events).toEqual([])
            expect(requests).toEqual([])
        })

        it('posts only the events of the team with a webhook and zapier in a mixed batch', async () => {
            await updateOrganizationAvailableFeatures(hub.postgres, organizationId, [ZAPIER])
            await updateOrganizationAvailableFeatures(hub.postgres, otherOrganizationId, [ZAPIER])
            const hookId = await createPageviewHook(team.id, 'https://hooks.zapier.com/team')
            await startService()

            const teamEvent = createIncomingEvent(team.id, { event: '$pageview' })
            const { events, requests } = await parseAndSend([createKafkaMessage(teamEvent), pageview(team2.id)])

            expect(events.map(({ teamId }) => teamId)).toEqual([team.id])
            expect(requests).toEqual([
                {
                    url: 'https://hooks.zapier.com/team',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: expect.objectContaining({
                        hook: { id: hookId, event: 'action_performed', target: 'https://hooks.zapier.com/team' },
                        data: expect.objectContaining({
                            teamId: team.id,
                            eventUuid: teamEvent.uuid,
                        }),
                    }),
                },
            ])
        })

        it('posts to the hook of every matching action', async () => {
            await updateOrganizationAvailableFeatures(hub.postgres, organizationId, [ZAPIER])
            await createPageviewHook(team.id, 'https://hooks.zapier.com/first')
            await createPageviewHook(team.id, 'https://hooks.zapier.com/second')
            await startService()

            const { requests } = await parseAndSend([pageview(team.id)])

            expect(requests.map(({ url }) => url).sort()).toEqual([
                'https://hooks.zapier.com/first',
                'https://hooks.zapier.com/second',
            ])
        })

        it('deletes only the hook whose target answers 410', async () => {
            await updateOrganizationAvailableFeatures(hub.postgres, organizationId, [ZAPIER])
            const goneHookId = await createPageviewHook(team.id, 'https://hooks.zapier.com/gone')
            const liveHookId = await createPageviewHook(team.id, 'https://hooks.zapier.com/live')
            const otherTeamHookId = await createPageviewHook(team2.id, 'https://hooks.zapier.com/other-team')
            await startService()
            mockFetch.mockImplementation((url) =>
                Promise.resolve(fetchResponse(url === 'https://hooks.zapier.com/gone' ? 410 : 200))
            )

            await parseAndSend([pageview(team.id)])

            expect(await storedHookIds([goneHookId, liveHookId, otherTeamHookId])).toEqual(
                [liveHookId, otherTeamHookId].sort()
            )
        })

        it('posts an identical payload regardless of group_analytics and never adds a groups key', async () => {
            await startService()
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
            await parseAndSend([makeMessage()])
            const bodyWithGroupAnalytics = parseJSON(mockFetch.mock.calls[0][1].body)

            mockFetch.mockClear()

            // group_analytics OFF (zapier still ON) — the non-group case
            hub.teamManager.hasAvailableFeature = jest
                .fn()
                .mockImplementation((_teamId, feature) => Promise.resolve(feature === 'zapier'))
            await parseAndSend([makeMessage()])
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

        beforeEach(async () => {
            await startService()
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

        beforeEach(async () => {
            await startService()
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

        it('should not fire webhooks when zapier feature is disabled', async () => {
            const hook = createMockHook(team.id)
            const action = createMockAction(team.id, { hooks: [hook] })

            hub.teamManager.hasAvailableFeature = jest.fn().mockResolvedValue(false)

            await service['fireWebhooks'](event, [action])

            expect(mockFetch).not.toHaveBeenCalled()
        })
    })

    describe('postWebhook', () => {
        let event: PostIngestionEvent

        beforeEach(async () => {
            await startService()
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
