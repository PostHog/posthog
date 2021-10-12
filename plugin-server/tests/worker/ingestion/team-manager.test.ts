import { mocked } from 'ts-jest/utils'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'
import { resetTestDatabase } from '../../helpers/sql'

describe('TeamManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let teamManager: TeamManager

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        teamManager = hub.teamManager
    })
    afterEach(async () => {
        await closeHub()
    })

    describe('fetchTeam()', () => {
        it('fetches and caches the team', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(hub.db, 'postgresQuery')

            let team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await hub.db.postgresQuery("UPDATE posthog_team SET name = 'Updated Name!'", undefined, 'testTag')

            mocked(hub.db.postgresQuery).mockClear()

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('Updated Name!')
            // expect(team!.__fetch_event_uuid).toEqual('uuid3')

            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('returns null when no such team', async () => {
            expect(await teamManager.fetchTeam(-1)).toEqual(null)
        })
    })

    describe('shouldSendWebhooks()', () => {
        it('returns false if unknown team', async () => {
            expect(await teamManager.shouldSendWebhooks(-1)).toEqual(false)
        })

        it('returns false if no hooks set up and team.slack_incoming_webhook == false', async () => {
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)
        })

        it('returns true if hooks are set up', async () => {
            await hub.db.postgresQuery('UPDATE posthog_team SET slack_incoming_webhook = true', undefined, 'testTag')
            await hub.db.postgresQuery(
                "INSERT INTO ee_hook (id, team_id, user_id, event, target, created, updated) VALUES('test_hook', 2, 1001, 'action_performed', 'http://example.com', now(), now())",
                undefined,
                'testTag'
            )

            expect(await teamManager.shouldSendWebhooks(2)).toEqual(true)
        })

        it('caches results, webhooks-only case', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(hub.db, 'postgresQuery')

            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)

            await hub.db.postgresQuery(
                "UPDATE posthog_team SET slack_incoming_webhook = 'https://x.com/'",
                undefined,
                'testTag'
            )
            mocked(hub.db.postgresQuery).mockClear()

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:10').getTime())
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:45').getTime())
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(true)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('caches results, Zapier hooks-only case', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(hub.db, 'postgresQuery')

            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)

            await hub.db.postgresQuery(
                "INSERT INTO ee_hook (id, team_id, user_id, event, target, created, updated) VALUES('test_hook', 2, 1001, 'action_performed', 'http://example.com', now(), now())",
                undefined,
                'testTag'
            )
            mocked(hub.db.postgresQuery).mockClear()

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:10').getTime())
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(false)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:45').getTime())
            expect(await teamManager.shouldSendWebhooks(2)).toEqual(true)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(2)
        })
    })

    describe('updateEventNamesAndProperties()', () => {
        let posthog: any

        beforeEach(async () => {
            posthog = { capture: jest.fn(), identify: jest.fn() }
            await hub.db.postgresQuery("UPDATE posthog_team SET ingested_event = 't'", undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_eventdefinition', undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_propertydefinition', undefined, 'testTag')
            await hub.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5)`,
                [new UUIDT().toString(), '$pageview', 3, 2, 2],
                'testTag'
            )
            await hub.db.postgresQuery(
                `INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6)`,
                [new UUIDT().toString(), 'property_name', false, null, null, 2],
                'testTag'
            )
            await hub.db.postgresQuery(
                `INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6)`,
                [new UUIDT().toString(), 'numeric_prop', true, null, null, 2],
                'testTag'
            )
        })

        it('updates event properties', async () => {
            await teamManager.updateEventNamesAndProperties(2, 'new-event', {
                property_name: 'efg',
                number: 4,
                numeric_prop: 5,
            })
            teamManager.teamCache.clear()

            expect(await hub.db.fetchEventDefinitions()).toEqual([
                {
                    id: expect.any(String),
                    name: '$pageview',
                    query_usage_30_day: 2,
                    team_id: 2,
                    volume_30_day: 3,
                },
                {
                    id: expect.any(String),
                    name: 'new-event',
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
            ])
            expect(await hub.db.fetchPropertyDefinitions()).toEqual([
                {
                    id: expect.any(String),
                    is_numerical: false,
                    name: 'property_name',
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
                {
                    id: expect.any(String),
                    is_numerical: true,
                    name: 'numeric_prop',
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
                {
                    id: expect.any(String),
                    is_numerical: true,
                    name: 'number',
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
            ])
        })

        it('does not update anything if nothing changes', async () => {
            await teamManager.fetchTeam(2)
            await teamManager.cacheEventNamesAndProperties(2)
            jest.spyOn(hub.db, 'postgresQuery')

            await teamManager.updateEventNamesAndProperties(2, '$pageview', {})

            expect(hub.db.postgresQuery).not.toHaveBeenCalled()
        })

        it('does not capture event', async () => {
            await teamManager.updateEventNamesAndProperties(2, 'new-event', { property_name: 'efg', number: 4 })

            expect(posthog.identify).not.toHaveBeenCalled()
            expect(posthog.capture).not.toHaveBeenCalled()
        })

        it('handles cache invalidation properly', async () => {
            await teamManager.fetchTeam(2)
            await teamManager.cacheEventNamesAndProperties(2)
            await hub.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, NULL, NULL, $3) ON CONFLICT DO NOTHING`,
                [new UUIDT().toString(), '$foobar', 2],
                'insertEventDefinition'
            )

            jest.spyOn(teamManager, 'fetchTeam')
            jest.spyOn(hub.db, 'postgresQuery')

            // Scenario: Different request comes in, team gets reloaded in the background with no updates
            await teamManager.updateEventNamesAndProperties(2, '$foobar', {})
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(1)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)

            // Scenario: Next request but a real update
            mocked(teamManager.fetchTeam).mockClear()
            mocked(hub.db.postgresQuery).mockClear()

            await teamManager.updateEventNamesAndProperties(2, '$newevent', {})
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(1)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        describe('first event has not yet been ingested', () => {
            beforeEach(async () => {
                await hub.db.postgresQuery('UPDATE posthog_team SET ingested_event = false', undefined, 'testTag')
            })

            it('calls posthog.identify and posthog.capture', async () => {
                await teamManager.updateEventNamesAndProperties(2, 'new-event', {})

                const team = await teamManager.fetchTeam(2)
                expect(posthog.identify).toHaveBeenCalledWith('plugin_test_user_distinct_id_1001')
                expect(posthog.capture).toHaveBeenCalledWith('first team event ingested', { team: team!.uuid })
            })
        })
    })
})
