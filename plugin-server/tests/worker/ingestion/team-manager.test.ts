import { DateTime, Settings } from 'luxon'

import { DateTimePropertyTypeFormat, Hub, PropertyType } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { posthog } from '../../../src/utils/posthog'
import { UUIDT } from '../../../src/utils/utils'
import {
    dateTimePropertyTypeFormatPatterns,
    isNumericString,
} from '../../../src/worker/ingestion/property-definitions-auto-discovery'
import { NULL_AFTER_PROPERTY_TYPE_DETECTION } from '../../../src/worker/ingestion/property-definitions-cache'
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
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        teamManager = hub.teamManager
        Settings.defaultZoneName = 'utc'
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

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:55Z').getTime())
            await hub.db.postgresQuery("UPDATE posthog_team SET name = 'Updated Name!'", undefined, 'testTag')

            jest.mocked(hub.db.postgresQuery).mockClear()

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:02:06Z').getTime())

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
            await hub.db.postgresQuery('DELETE FROM posthog_eventproperty', undefined, 'testTag')
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
            await hub.db.postgresQuery(
                `INSERT INTO posthog_eventproperty (event, property, team_id) VALUES ($1, $2, $3)`,
                ['new-event', 'numeric_prop', 2],
                'testTag'
            )
        })

        it('updates event properties', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:36.000Z').getTime())

            await teamManager.updateEventNamesAndProperties(2, 'new-event', {
                property_name: 'efg',
                number: 4,
                numeric_prop: 5,
            })
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

            expect(await hub.db.fetchEventProperties()).toEqual([
                {
                    id: expect.any(Number),
                    event: 'new-event',
                    property: 'numeric_prop',
                    team_id: 2,
                },
                {
                    id: expect.any(Number),
                    event: 'new-event',
                    property: 'property_name',
                    team_id: 2,
                },
                {
                    id: expect.any(Number),
                    event: 'new-event',
                    property: 'number',
                    team_id: 2,
                },
            ])

            expect(await hub.db.fetchPropertyDefinitions()).toEqual([
                {
                    id: expect.any(String),
                    is_numerical: false,
                    name: 'property_name',
                    property_type: 'String',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
                {
                    id: expect.any(String),
                    is_numerical: true,
                    name: 'number',
                    property_type: 'Numeric',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
                {
                    id: expect.any(String),
                    is_numerical: true,
                    name: 'numeric_prop',
                    property_type: 'Numeric',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: 2,
                    volume_30_day: null,
                },
            ])
        })

        it('sets or updates eventLastSeenCache', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2015-04-04T04:04:04.000Z').getTime())

            expect(teamManager.eventLastSeenCache.length).toEqual(0)
            await teamManager.updateEventNamesAndProperties(2, 'another_test_event', {})
            expect(teamManager.eventLastSeenCache.length).toEqual(1)
            expect(teamManager.eventLastSeenCache.get('[2,"another_test_event"]')).toEqual(20150404)

            // Start tracking queries
            const postgresQuery = jest.spyOn(teamManager.db, 'postgresQuery')

            // New event, 10 sec later (all caches should be hit)
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2015-04-04T04:04:14.000Z').getTime())
            await teamManager.updateEventNamesAndProperties(2, 'another_test_event', {})
            expect(postgresQuery).not.toHaveBeenCalled()

            // New event, 1 day later (all caches should be empty)
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2015-04-05T04:04:14.000Z').getTime())
            await teamManager.updateEventNamesAndProperties(2, 'another_test_event', {})
            expect(postgresQuery).toHaveBeenCalledWith(
                'UPDATE posthog_eventdefinition SET last_seen_at=$1 WHERE team_id=$2 AND name=$3',
                [DateTime.now(), 2, 'another_test_event'],
                'updateEventLastSeenAt'
            )

            // Re-ingest, should add no queries
            postgresQuery.mockClear()
            await teamManager.updateEventNamesAndProperties(2, 'another_test_event', {})
            expect(postgresQuery).not.toHaveBeenCalled()

            expect(teamManager.eventLastSeenCache.length).toEqual(1)
            expect(teamManager.eventLastSeenCache.get('[2,"another_test_event"]')).toEqual(20150405)
        })

        it('does not capture event', async () => {
            await teamManager.updateEventNamesAndProperties(2, 'new-event', { property_name: 'efg', number: 4 })

            expect(posthog.capture).not.toHaveBeenCalled()
        })

        it('handles cache invalidation properly', async () => {
            await teamManager.fetchTeam(2)
            await teamManager.cacheEventNamesAndProperties(2, '$foobar')
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
            jest.mocked(teamManager.fetchTeam).mockClear()
            jest.mocked(hub.db.postgresQuery).mockClear()

            await teamManager.updateEventNamesAndProperties(2, '$newevent', {})
            expect(teamManager.fetchTeam).toHaveBeenCalledTimes(1)
            // extra query for `cacheEventNamesAndProperties` that we did manually before
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(2)
        })

        describe('first event has not yet been ingested', () => {
            beforeEach(async () => {
                await hub.db.postgresQuery('UPDATE posthog_team SET ingested_event = false', undefined, 'testTag')
            })

            it('calls posthog.identify and posthog.capture', async () => {
                await teamManager.updateEventNamesAndProperties(2, 'new-event', {
                    $lib: 'python',
                    $host: 'localhost:8000',
                })

                const team = await teamManager.fetchTeam(2)
                expect(posthog.capture).toHaveBeenCalledWith({
                    distinctId: 'plugin_test_user_distinct_id_1001',
                    event: 'first team event ingested',
                    properties: {
                        team: team!.uuid,
                        host: 'localhost:8000',
                        realm: undefined,
                        sdk: 'python',
                    },
                    groups: {
                        organization: 'ca30f2ec-e9a4-4001-bf27-3ef194086068',
                        project: team!.uuid,
                        instance: 'unknown',
                    },
                })
            })
        })

        describe('auto-detection of property types', () => {
            const insertPropertyDefinitionQuery = `
INSERT INTO posthog_propertydefinition
(id, name, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type)
VALUES ($1, $2, $3, NULL, NULL, $4, $5)
ON CONFLICT ON CONSTRAINT posthog_propertydefinition_team_id_name_e21599fc_uniq
DO UPDATE SET property_type=$5 WHERE posthog_propertydefinition.property_type IS NULL`
            const teamId = 2

            const randomInteger = () => Math.floor(Math.random() * 1000) + 1
            const randomString = () => [...Array(10)].map(() => (~~(Math.random() * 36)).toString(36)).join('')

            const expectMockQueryCallToMatch = (
                expected: { query: string; tag: string; params: any[] },
                postgresQuery: jest.SpyInstance,
                callIndex?: number | undefined
            ) => {
                const [query, queryParams, queryTag] =
                    postgresQuery.mock.calls[callIndex || postgresQuery.mock.calls.length - 1]
                expect(queryTag).toEqual(expected.tag)
                expect(queryParams).toEqual(expected.params)
                expect(query).toEqual(expected.query)
            }

            let postgresQuery: jest.SpyInstance
            beforeEach(() => {
                postgresQuery = jest.spyOn(teamManager.db, 'postgresQuery')
            })

            it('adds no type for objects', async () => {
                await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    anObjectProperty: { anything: randomInteger() },
                })

                expect(teamManager.propertyDefinitionsCache.get(teamId)?.peek('anObjectProperty')).toEqual(
                    NULL_AFTER_PROPERTY_TYPE_DETECTION
                )

                expectMockQueryCallToMatch(
                    {
                        tag: 'insertPropertyDefinition',
                        query: insertPropertyDefinitionQuery,
                        params: [expect.any(String), 'anObjectProperty', false, teamId, null],
                    },
                    postgresQuery
                )
            })

            const boolTestCases = [
                true,
                false,
                'true',
                'false',
                'True',
                'False',
                'TRUE',
                'FALSE',
                ' true ',
                ' false',
                'true ',
            ]
            boolTestCases.forEach((testcase) => {
                it(`identifies ${testcase} as a boolean`, async () => {
                    await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                        some_bool: testcase,
                    })

                    expect(teamManager.propertyDefinitionsCache.get(teamId)?.peek('some_bool')).toEqual('Boolean')

                    expectMockQueryCallToMatch(
                        {
                            tag: 'insertPropertyDefinition',
                            query: insertPropertyDefinitionQuery,
                            params: [expect.any(String), 'some_bool', false, teamId, 'Boolean'],
                        },
                        postgresQuery
                    )
                })
            })

            // i.e. not using truthiness to detect whether something is boolean
            const notBoolTestCases = [0, 1, '0', '1', 'yes', 'no', null, undefined, '', [], ' ']
            notBoolTestCases.forEach((testcase) => {
                it(`does not identify ${testcase} as a boolean`, async () => {
                    await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                        some_bool: testcase,
                    })

                    expect(teamManager.propertyDefinitionsCache.get(teamId)?.peek('some_bool')).not.toEqual('Boolean')
                })
            })

            it('identifies a numeric type', async () => {
                await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    some_number: randomInteger(),
                })

                expect(teamManager.propertyDefinitionsCache.get(teamId)?.peek('some_number')).toEqual('Numeric')

                expectMockQueryCallToMatch(
                    {
                        tag: 'insertPropertyDefinition',
                        query: insertPropertyDefinitionQuery,
                        params: [expect.any(String), 'some_number', true, teamId, 'Numeric'],
                    },
                    postgresQuery
                )
            })

            it('identifies a numeric type sent as a string', async () => {
                await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    some_number: String(randomInteger()),
                })

                expect(teamManager.propertyDefinitionsCache.get(teamId)?.peek('some_number')).toEqual('Numeric')

                expectMockQueryCallToMatch(
                    {
                        tag: 'insertPropertyDefinition',
                        query: insertPropertyDefinitionQuery,
                        params: [expect.any(String), 'some_number', true, teamId, 'Numeric'],
                    },
                    postgresQuery
                )
            })

            it('identifies a string type', async () => {
                await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    some_string: randomString(),
                })

                expect(teamManager.propertyDefinitionsCache.get(teamId)?.peek('some_string')).toEqual('String')

                expectMockQueryCallToMatch(
                    {
                        tag: 'insertPropertyDefinition',
                        query: insertPropertyDefinitionQuery,
                        params: [expect.any(String), 'some_string', false, teamId, 'String'],
                    },
                    postgresQuery
                )
            })

            // there are several cases that can be identified as timestamps
            // and each might match with time or timestamp in the property key
            // but won't match if neither is in it
            const unixTimestampTestCases = [
                {
                    propertyKey: 'unix timestamp with fractional seconds as a number',
                    date: 1234567890.123,
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp with five decimal places of fractional seconds as a number',
                    date: 1234567890.12345,
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp as a number',
                    date: 1234567890,
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp with fractional seconds as a string',
                    date: '1234567890.123',
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp with five decimal places of fractional seconds as a string',
                    date: '1234567890.12345',
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp as a string',
                    date: '1234567890',
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp in milliseconds as a number',
                    date: 1234567890123,
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp in milliseconds as a string',
                    date: '1234567890123',
                    expectedPropertyType: PropertyType.DateTime,
                },
            ].flatMap((testcase) => {
                const toEdit = testcase

                const toMatchWithJustTimeInName = {
                    ...toEdit,
                    propertyKey: testcase.propertyKey.replace('timestamp', 'time'),
                }

                const toNotMatch = {
                    ...toEdit,
                    propertyKey: toEdit.propertyKey.replace('timestamp', 'as a string'),
                    expectedPropertyType: isNumericString(toEdit.date) ? PropertyType.Numeric : PropertyType.String,
                }

                return [testcase, toMatchWithJustTimeInName, toNotMatch]
            })

            unixTimestampTestCases.forEach((testcase) => {
                it(`with key ${testcase.propertyKey} matches ${testcase.date} as ${testcase.expectedPropertyType}`, async () => {
                    const properties: Record<string, string | number> = {}
                    properties[testcase.propertyKey] = testcase.date
                    await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', properties)

                    expectMockQueryCallToMatch(
                        {
                            tag: 'insertPropertyDefinition',
                            query: insertPropertyDefinitionQuery,
                            params: [
                                expect.any(String),
                                testcase.propertyKey,
                                testcase.expectedPropertyType === PropertyType.Numeric,
                                teamId,
                                testcase.expectedPropertyType,
                            ],
                        },
                        postgresQuery
                    )
                })
            })

            // most datetimes can be identified by replacing the date parts with numbers
            // RFC 822 formatted dates as it has a short name for the month instead of a two-digit number
            const dateTimeFormatTestCases: {
                propertyKey: string
                date: string
            }[] = Object.keys(dateTimePropertyTypeFormatPatterns).flatMap((patternEnum: string) => {
                const patternDescription: string =
                    DateTimePropertyTypeFormat[patternEnum as keyof typeof DateTimePropertyTypeFormat]
                if (patternDescription === 'rfc_822') {
                    return {
                        propertyKey: 'an_rfc_822_format_date',
                        date: 'Wed, 02 Oct 2002 15:00:00 +0200',
                    }
                } else if (patternDescription === DateTimePropertyTypeFormat.ISO8601_DATE) {
                    return [
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233056+00',
                            date: '2022-01-15T11:18:49.233056+00:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233056-00',
                            date: '2022-01-15T11:18:49.233056-00:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233056+04',
                            date: '2022-01-15T11:18:49.233056+04:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233056-04',
                            date: '2022-01-15T11:18:49.233056-04:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233056z',
                            date: '2022-01-15T11:18:49.233056z',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233+00:00',
                            date: '2022-01-15T11:18:49.233+00:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233-00:00',
                            date: '2022-01-15T11:18:49.233-00:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233+04:00',
                            date: '2022-01-15T11:18:49.233+04:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233-04:00',
                            date: '2022-01-15T11:18:49.233-04:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49.233z',
                            date: '2022-01-15T11:18:49.233z',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49+00:00',
                            date: '2022-01-15T11:18:49+00:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49-00:00',
                            date: '2022-01-15T11:18:49-00:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49+04:00',
                            date: '2022-01-15T11:18:49+04:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49-04:00',
                            date: '2022-01-15T11:18:49-04:00',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49z',
                            date: '2022-01-15T11:18:49z',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49+11',
                            date: '2022-01-15T11:18:49+11',
                        },
                        {
                            propertyKey: 'an_iso_8601_format_date_2022-01-15T11:18:49+0530',
                            date: '2022-01-15T11:18:49+0530',
                        },
                    ]
                } else {
                    const date = patternDescription
                        .replace('YYYY', '2021')
                        .replace('MM', '04')
                        .replace('DD', '01')
                        .replace('hh', '13')
                        .replace('mm', '01')
                        .replace('ss', '01')

                    //iso timestamps can have fractional parts of seconds
                    if (date.includes('T')) {
                        return [
                            { propertyKey: patternDescription, date },
                            { propertyKey: patternDescription, date: date.replace('Z', '.243Z') },
                        ]
                    } else {
                        return { propertyKey: patternDescription, date }
                    }
                }
            })

            dateTimeFormatTestCases.forEach((testcase) => {
                it(`matches ${testcase.date} as DateTime`, async () => {
                    const properties: Record<string, string> = {}
                    properties[testcase.propertyKey] = testcase.date
                    await teamManager.updateEventNamesAndProperties(teamId, 'another_test_event', properties)

                    expectMockQueryCallToMatch(
                        {
                            tag: 'insertPropertyDefinition',
                            query: insertPropertyDefinitionQuery,
                            params: [expect.any(String), testcase.propertyKey, false, teamId, PropertyType.DateTime],
                        },
                        postgresQuery
                    )
                })
            })

            it('does identify type if the property was previously saved with no type', async () => {
                await teamManager.db.postgresQuery(
                    'INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type) VALUES ($1, $2, $3, NULL, NULL, $4, $5)',
                    [new UUIDT().toString(), 'a_timestamp', false, teamId, null],
                    'testTag'
                )

                await teamManager.updateEventNamesAndProperties(teamId, 'a_test_event', {
                    a_timestamp: 1234567890,
                })

                const results = await teamManager.db.postgresQuery(
                    `
                    SELECT property_type from posthog_propertydefinition
                    where name=$1
                `,
                    ['a_timestamp'],
                    'queryForProperty'
                )
                expect(results.rows[0]).toEqual({ property_type: 'DateTime' })
            })

            it('does not replace property type if the property was previously saved with a different type', async () => {
                await teamManager.db.postgresQuery(
                    'INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type) VALUES ($1, $2, $3, NULL, NULL, $4, $5)',
                    [new UUIDT().toString(), 'a_prop_with_type', false, teamId, PropertyType.DateTime],
                    'testTag'
                )

                await teamManager.updateEventNamesAndProperties(teamId, 'a_test_event', {
                    a_prop_with_type: 1234567890,
                })

                const results = await teamManager.db.postgresQuery(
                    `
                    SELECT property_type from posthog_propertydefinition
                    where name=$1
                `,
                    ['a_prop_with_type'],
                    'queryForProperty'
                )
                expect(results.rows[0]).toEqual({
                    property_type: PropertyType.DateTime,
                })
            })

            it('does not keep trying to set a property type when it cannot', async () => {
                const properties = {
                    a_prop_with_a_type_we_do_not_set: { a: 1234567890 },
                }
                await teamManager.updateEventNamesAndProperties(teamId, 'a_test_event', properties)

                // 7 calls to DB to set up team manager and updateEventNamesAndProperties
                expect(postgresQuery.mock.calls).toHaveLength(7)

                await teamManager.updateEventNamesAndProperties(teamId, 'a_test_event', properties)

                // no more calls to DB as everything is cached
                expect(postgresQuery.mock.calls).toHaveLength(7)
            })
        })
    })
})
