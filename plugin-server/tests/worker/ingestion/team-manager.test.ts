import { DateTime } from 'luxon'
import { mocked } from 'ts-jest/utils'

import { defaultConfig } from '../../../src/config/config'
import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { posthog } from '../../../src/utils/posthog'
import { UUIDT } from '../../../src/utils/utils'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/posthog', () => ({
    posthog: {
        identify: jest.fn(),
        capture: jest.fn(),
    },
}))

describe('TeamManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let teamManager: TeamManager

    beforeEach(async () => {
        // TODO: #7422 remove experimental config
        ;[hub, closeHub] = await createHub({ ...defaultConfig, EXPERIMENTAL_EVENTS_LAST_SEEN_ENABLED_TEAMS: '2,3' })
        await resetTestDatabase()
        teamManager = hub.teamManager
    })

    afterEach(async () => {
        await closeHub()
    })

    describe('fetchTeam()', () => {
        it('fetches and caches the team', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:05Z').getTime())
            jest.spyOn(hub.db, 'postgresQuery')

            let team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:25Z').getTime())
            await hub.db.postgresQuery("UPDATE posthog_team SET name = 'Updated Name!'", undefined, 'testTag')

            mocked(hub.db.postgresQuery).mockClear()

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:36Z').getTime())

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('Updated Name!')
            // expect(team!.__fetch_event_uuid).toEqual('uuid3')

            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('returns null when no such team', async () => {
            expect(await teamManager.fetchTeam(-1)).toEqual(null)
        })
    })

    describe('updateEventNamesAndProperties()', () => {
        beforeEach(async () => {
            await hub.db.postgresQuery("UPDATE posthog_team SET ingested_event = 't'", undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_eventdefinition', undefined, 'testTag')
            await hub.db.postgresQuery('DELETE FROM posthog_propertydefinition', undefined, 'testTag')
            await hub.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, created_at) VALUES ($1, $2, $3, $4, $5, NOW())`,
                [new UUIDT().toString(), '$pageview', 3, 2, 2],
                'testTag'
            )
            await hub.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, team_id, created_at, last_seen_at) VALUES ($1, $2, $3, NOW(), $4)`,
                [new UUIDT().toString(), 'another_test_event', 2, '2014-03-23T23:23:23Z'],
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
            await teamManager.updateEventNamesAndProperties(
                2,
                'new-event',
                {
                    property_name: 'efg',
                    number: 4,
                    numeric_prop: 5,
                },
                DateTime.now()
            )
            teamManager.teamCache.clear()

            const eventDefinitions = await hub.db.fetchEventDefinitions()

            expect(eventDefinitions).toEqual([
                {
                    id: expect.any(String),
                    name: '$pageview',
                    query_usage_30_day: 2,
                    team_id: 2,
                    volume_30_day: 3,
                    last_seen_at: null,
                    created_at: expect.any(String),
                },
                {
                    id: expect.any(String),
                    name: 'another_test_event',
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                    last_seen_at: '2014-03-23T23:23:23.000Z', // values are not updated directly
                    created_at: expect.any(String),
                },
                {
                    id: expect.any(String),
                    name: 'new-event',
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                    last_seen_at: '2020-02-27T11:00:36.000Z', // overridden Date.now()
                    created_at: expect.any(String),
                },
            ])

            for (const eventDef of eventDefinitions) {
                if (eventDef.name === 'new-event') {
                    const parsedLastSeen = DateTime.fromISO(eventDef.last_seen_at)
                    expect(parsedLastSeen.diff(DateTime.now()).seconds).toBeCloseTo(0)

                    const parsedCreatedAt = DateTime.fromISO(eventDef.created_at)
                    expect(parsedCreatedAt.diff(DateTime.now()).seconds).toBeCloseTo(0)
                }
            }

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

        it('sets or updates last_seen_cache on event', async () => {
            // Existing event
            await teamManager.updateEventNamesAndProperties(
                2,
                'another_test_event',
                {},
                DateTime.fromISO('2015-04-04T04:04:04.000Z')
            )

            expect(teamManager.eventLastSeenCache.size).toEqual(1)
            expect(teamManager.eventLastSeenCache.get('2_another_test_event')).toEqual(1428120244000)

            // New event
            await teamManager.updateEventNamesAndProperties(
                2,
                'another_test_event',
                {},
                DateTime.fromISO('2015-04-04T05:05:05.000Z')
            )
            expect(teamManager.eventLastSeenCache.size).toEqual(1)
            expect(teamManager.eventLastSeenCache.get('2_another_test_event')).toEqual(1428123905000)
        })

        it('does not set last_seen_cache on new event', async () => {
            // last_seen_at is set in the same INSERT statement, so we don't need to update it

            await teamManager.updateEventNamesAndProperties(
                2,
                'this_is_new_3881',
                {},
                DateTime.fromISO('2018-01-01T12:12:12.000Z')
            )
            expect(teamManager.eventLastSeenCache.size).toEqual(0)
        })

        it('does not update last_seen_cache if event timestamp is older', async () => {
            jest.spyOn(hub.db, 'postgresQuery')
            await teamManager.updateEventNamesAndProperties(
                2,
                'another_test_event',
                {},
                DateTime.fromISO('2014-03-23T23:23:23.000Z')
            )

            // Try to set an older time
            await teamManager.updateEventNamesAndProperties(
                2,
                'another_test_event',
                {},
                DateTime.fromISO('2014-03-23T23:23:00.000Z')
            )

            expect(teamManager.eventLastSeenCache.size).toEqual(1)
            expect(teamManager.eventLastSeenCache.get('2_another_test_event')).toEqual(1395617003000)
        })

        it('flushes last_seen_cache properly', async () => {
            // TODO: Test
        })

        it('does not capture event', async () => {
            await teamManager.updateEventNamesAndProperties(
                2,
                'new-event',
                { property_name: 'efg', number: 4 },
                DateTime.now()
            )

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
            await teamManager.updateEventNamesAndProperties(2, '$foobar', {}, DateTime.now())
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(1)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)

            // Scenario: Next request but a real update
            mocked(teamManager.fetchTeam).mockClear()
            mocked(hub.db.postgresQuery).mockClear()

            await teamManager.updateEventNamesAndProperties(2, '$newevent', {}, DateTime.now())
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(1)
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        describe('first event has not yet been ingested', () => {
            beforeEach(async () => {
                await hub.db.postgresQuery('UPDATE posthog_team SET ingested_event = false', undefined, 'testTag')
            })

            it('calls posthog.identify and posthog.capture', async () => {
                await teamManager.updateEventNamesAndProperties(
                    2,
                    'new-event',
                    {
                        $lib: 'python',
                        $host: 'localhost:8000',
                    },
                    DateTime.now()
                )

                const team = await teamManager.fetchTeam(2)
                expect(posthog.identify).toHaveBeenCalledWith('plugin_test_user_distinct_id_1001')
                expect(posthog.capture).toHaveBeenCalledWith('first team event ingested', {
                    team: team!.uuid,
                    host: 'localhost:8000',
                    realm: undefined,
                    sdk: 'python',
                    $groups: {
                        organization: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
                        project: team!.uuid,
                        instance: 'unknown',
                    },
                })
            })
        })
    })
})
