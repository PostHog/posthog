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
import { Hub, ISOTimestamp, PostIngestionEvent, ProjectId, Team } from '../../types'
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

    const pageviewEvent = (teamId: number): PostIngestionEvent => ({
        eventUuid: randomUUID(),
        event: '$pageview',
        teamId,
        distinctId: 'test-user',
        properties: {},
        timestamp: new Date().toISOString() as ISOTimestamp,
        projectId: teamId as ProjectId,
        person_created_at: null,
        person_properties: {},
        person_id: undefined,
    })

    const deleteTeamRows = async (teamId: number): Promise<void> => {
        for (const table of ['ee_hook', 'posthog_action']) {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM ${table} WHERE team_id = $1`,
                [teamId],
                'deleteTestRows'
            )
        }
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            'DELETE FROM posthog_team WHERE id = $1',
            [teamId],
            'deleteTestTeam'
        )
    }

    const sentRequests = () =>
        mockFetch.mock.calls.map(([url, init]) => ({
            url,
            method: init?.method,
            headers: init?.headers,
            body: parseJSON(init?.body as string),
        }))

    const parseAndSend = async (messages: Message[]) => {
        const events = await service.parseBatch(messages)
        await service.processEvents(events).backgroundTask
        return { events, requests: sentRequests() }
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

        it('posts to the hook of every matching action that has a target', async () => {
            await updateOrganizationAvailableFeatures(hub.postgres, organizationId, [ZAPIER])
            await createPageviewHook(team.id, 'https://hooks.zapier.com/first')
            await createPageviewHook(team.id, 'https://hooks.zapier.com/second')
            await createPageviewHook(team.id, '')
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

        it('fails the background task when a webhook request errors', async () => {
            await updateOrganizationAvailableFeatures(hub.postgres, organizationId, [ZAPIER])
            await createPageviewHook(team.id, 'https://hooks.zapier.com/team')
            await startService()
            mockFetch.mockRejectedValue(new Error('Network error'))

            const events = await service.parseBatch([pageview(team.id)])

            await expect(service.processEvents(events).backgroundTask).rejects.toThrow('Network error')
        })

        it.each([
            { groupAnalytics: 'off', features: [ZAPIER] },
            { groupAnalytics: 'on', features: [ZAPIER, { key: 'group_analytics', name: 'Group analytics' }] },
        ])(
            'posts the event properties and no groups key with group analytics $groupAnalytics',
            async ({ features }) => {
                await updateOrganizationAvailableFeatures(hub.postgres, organizationId, features)
                await createPageviewHook(team.id, 'https://hooks.zapier.com/team')
                await startService()
                const properties = { $groups: { project: 'test-project-id' }, foo: 'bar' }

                const { requests } = await parseAndSend([
                    createKafkaMessage(
                        createIncomingEvent(team.id, { event: '$pageview', properties: JSON.stringify(properties) })
                    ),
                ])

                expect(requests).toHaveLength(1)
                const { data } = requests[0].body
                expect(Object.keys(data).sort()).toEqual([
                    'distinctId',
                    'elementsList',
                    'event',
                    'eventUuid',
                    'person',
                    'properties',
                    'teamId',
                    'timestamp',
                ])
                expect(data.properties).toMatchObject(properties)
            }
        )
    })

    describe('processEvents', () => {
        it('posts nothing for a team without zapier, even with a matching hook', async () => {
            await createPageviewHook(team.id, 'https://hooks.zapier.com/team')
            await startService()

            await service.processEvents([pageviewEvent(team.id)]).backgroundTask

            expect(sentRequests()).toEqual([])
        })

        it('posts nothing for a team deleted after its hooks loaded', async () => {
            await updateOrganizationAvailableFeatures(hub.postgres, otherOrganizationId, [ZAPIER])
            await createPageviewHook(team2.id, 'https://hooks.zapier.com/other-team')
            await startService()
            await deleteTeamRows(team2.id)

            await service.processEvents([pageviewEvent(team2.id)]).backgroundTask

            expect(sentRequests()).toEqual([])
        })
    })
})
