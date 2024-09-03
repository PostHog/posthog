import { DateTime, Settings } from 'luxon'

import { DateTimePropertyTypeFormat, Hub, PropertyDefinitionTypeEnum, PropertyType } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { posthog } from '../../../src/utils/posthog'
import { UUIDT } from '../../../src/utils/utils'
import { GroupTypeManager } from '../../../src/worker/ingestion/group-type-manager'
import { dateTimePropertyTypeFormatPatterns } from '../../../src/worker/ingestion/property-definitions-auto-discovery'
import { NULL_AFTER_PROPERTY_TYPE_DETECTION } from '../../../src/worker/ingestion/property-definitions-cache'
import { PropertyDefinitionsManager } from '../../../src/worker/ingestion/property-definitions-manager'
import { createOrganization, createTeam } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/posthog', () => ({
    posthog: {
        identify: jest.fn(),
        capture: jest.fn(),
    },
}))

describe('PropertyDefinitionsManager()', () => {
    let hub: Hub
    let manager: PropertyDefinitionsManager
    let teamId: number
    let organizationId: string
    let groupTypeManager: GroupTypeManager

    beforeEach(async () => {
        hub = await createHub()
        organizationId = await createOrganization(hub.db.postgres)
        teamId = await createTeam(hub.db.postgres, organizationId)
        groupTypeManager = new GroupTypeManager(hub.postgres, hub.teamManager, hub.SITE_URL)
        manager = new PropertyDefinitionsManager(hub.teamManager, groupTypeManager, hub.db, hub)

        Settings.defaultZoneName = 'utc'
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('updateEventNamesAndProperties()', () => {
        describe('base tests', () => {
            beforeEach(async () => {
                await hub.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, created_at) VALUES ($1, $2, $3, $4, $5, NOW())`,
                    [new UUIDT().toString(), '$pageview', 3, 2, teamId],
                    'testTag'
                )
                await hub.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_eventdefinition (id, name, team_id, created_at, last_seen_at) VALUES ($1, $2, $3, NOW(), $4)`,
                    [new UUIDT().toString(), 'another_test_event', teamId, '2014-03-23T23:23:23Z'],
                    'testTag'
                )
                await hub.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_propertydefinition (id, name, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7)`,
                    [
                        new UUIDT().toString(),
                        'property_name',
                        PropertyDefinitionTypeEnum.Event,
                        false,
                        null,
                        null,
                        teamId,
                    ],
                    'testTag'
                )
                await hub.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_propertydefinition (id, name, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7)`,
                    [
                        new UUIDT().toString(),
                        'numeric_prop',
                        PropertyDefinitionTypeEnum.Event,
                        true,
                        null,
                        null,
                        teamId,
                    ],
                    'testTag'
                )
                await hub.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_eventproperty (event, property, team_id) VALUES ($1, $2, $3)`,
                    ['new-event', 'numeric_prop', teamId],
                    'testTag'
                )
            })

            it('updates event properties', async () => {
                jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:36.000Z').getTime())

                await manager.updateEventNamesAndProperties(teamId, 'new-event', {
                    property_name: 'efg',
                    number: 4,
                    numeric_prop: 5,
                })

                const eventDefinitions = await hub.db.fetchEventDefinitions(teamId)

                expect(eventDefinitions).toEqual([
                    {
                        id: expect.any(String),
                        name: '$pageview',
                        query_usage_30_day: 2,
                        team_id: teamId,
                        volume_30_day: 3,
                        last_seen_at: null,
                        created_at: expect.any(String),
                    },
                    {
                        id: expect.any(String),
                        name: 'another_test_event',
                        query_usage_30_day: null,
                        team_id: teamId,
                        volume_30_day: null,
                        last_seen_at: '2014-03-23T23:23:23.000Z', // values are not updated directly
                        created_at: expect.any(String),
                    },
                    {
                        id: expect.any(String),
                        name: 'new-event',
                        query_usage_30_day: null,
                        team_id: teamId,
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

                expect(await hub.db.fetchEventProperties(teamId)).toEqual([
                    {
                        id: expect.any(Number),
                        event: 'new-event',
                        property: 'number',
                        team_id: teamId,
                    },
                    {
                        id: expect.any(Number),
                        event: 'new-event',
                        property: 'numeric_prop',
                        team_id: teamId,
                    },
                    {
                        id: expect.any(Number),
                        event: 'new-event',
                        property: 'property_name',
                        team_id: teamId,
                    },
                ])

                expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                    {
                        id: expect.any(String),
                        is_numerical: true,
                        name: 'number',
                        property_type: 'Numeric',
                        property_type_format: null,
                        query_usage_30_day: null,
                        team_id: teamId,
                        volume_30_day: null,
                        type: PropertyDefinitionTypeEnum.Event,
                        group_type_index: null,
                    },
                    {
                        id: expect.any(String),
                        is_numerical: true,
                        name: 'numeric_prop',
                        property_type: 'Numeric',
                        property_type_format: null,
                        query_usage_30_day: null,
                        team_id: teamId,
                        volume_30_day: null,
                        type: PropertyDefinitionTypeEnum.Event,
                        group_type_index: null,
                    },
                    {
                        id: expect.any(String),
                        is_numerical: false,
                        name: 'property_name',
                        property_type: 'String',
                        property_type_format: null,
                        query_usage_30_day: null,
                        team_id: teamId,
                        volume_30_day: null,
                        type: PropertyDefinitionTypeEnum.Event,
                        group_type_index: null,
                    },
                ])
            })

            it('sets or updates eventLastSeenCache', async () => {
                jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2015-04-04T04:04:04.000Z').getTime())

                expect(manager.eventLastSeenCache.length).toEqual(0)
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {})
                expect(manager.eventLastSeenCache.length).toEqual(1)
                expect(manager.eventLastSeenCache.get(`[${teamId},"another_test_event"]`)).toEqual(20150404)

                // Start tracking queries
                const postgresQuery = jest.spyOn(manager.db.postgres, 'query')

                // New event, 10 sec later (all caches should be hit)
                jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2015-04-04T04:04:14.000Z').getTime())
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {})
                expect(postgresQuery).not.toHaveBeenCalled()

                // New event, 1 day later (all caches should be empty)
                jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2015-04-05T04:04:14.000Z').getTime())
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {})
                expect(postgresQuery).toHaveBeenCalledWith(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_eventdefinition SET last_seen_at=$1 WHERE team_id=$2 AND name=$3',
                    [DateTime.now(), teamId, 'another_test_event'],
                    'updateEventLastSeenAt'
                )

                // Re-ingest, should add no queries
                postgresQuery.mockClear()
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {})
                expect(postgresQuery).not.toHaveBeenCalled()

                expect(manager.eventLastSeenCache.length).toEqual(1)
                expect(manager.eventLastSeenCache.get(`[${teamId},"another_test_event"]`)).toEqual(20150405)
            })

            it('does not capture event', async () => {
                await manager.updateEventNamesAndProperties(teamId, 'new-event', { property_name: 'efg', number: 4 })

                expect(posthog.capture).not.toHaveBeenCalled()
            })

            it('handles cache invalidation properly', async () => {
                await manager.teamManager.fetchTeam(teamId)
                await manager.cacheEventNamesAndProperties(teamId, '$foobar')
                await hub.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, NULL, NULL, $3) ON CONFLICT DO NOTHING`,
                    [new UUIDT().toString(), '$foobar', teamId],
                    'insertEventDefinition'
                )

                jest.spyOn(manager.teamManager, 'fetchTeam')
                jest.spyOn(hub.db.postgres, 'query')

                // Scenario: Different request comes in, team gets reloaded in the background with no updates
                await manager.updateEventNamesAndProperties(teamId, '$foobar', {})
                expect(manager.teamManager.fetchTeam).toHaveBeenCalledTimes(1)
                expect(hub.db.postgres.query).toHaveBeenCalledTimes(1)

                // Scenario: Next request but a real update
                jest.mocked(manager.teamManager.fetchTeam).mockClear()
                jest.mocked(hub.db.postgres.query).mockClear()

                await manager.updateEventNamesAndProperties(teamId, '$newevent', {})
                expect(manager.teamManager.fetchTeam).toHaveBeenCalledTimes(1)
                // extra query for `cacheEventNamesAndProperties` that we did manually before
                expect(hub.db.postgres.query).toHaveBeenCalledTimes(2)
            })
        })

        it('saves person property definitions', async () => {
            await manager.updateEventNamesAndProperties(teamId, 'new-event', {
                $set: {
                    foo: 'bar',
                },
                $set_once: {
                    numeric: 123,
                },
            })

            expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                {
                    id: expect.any(String),
                    is_numerical: false,
                    name: 'foo',
                    property_type: 'String',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: teamId,
                    volume_30_day: null,
                    type: PropertyDefinitionTypeEnum.Person,
                    group_type_index: null,
                },
                {
                    id: expect.any(String),
                    is_numerical: true,
                    name: 'numeric',
                    property_type: 'Numeric',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: teamId,
                    volume_30_day: null,
                    type: PropertyDefinitionTypeEnum.Person,
                    group_type_index: null,
                },
            ])
        })

        it('saves group property definitions', async () => {
            await groupTypeManager.insertGroupType(teamId, 'project', 0)
            await groupTypeManager.insertGroupType(teamId, 'organization', 1)

            await manager.updateEventNamesAndProperties(teamId, '$groupidentify', {
                $group_type: 'organization',
                $group_key: 'org::5',
                $group_set: {
                    foo: 'bar',
                    numeric: 3,
                },
            })

            expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                {
                    id: expect.any(String),
                    is_numerical: false,
                    name: 'foo',
                    property_type: 'String',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: teamId,
                    volume_30_day: null,
                    type: PropertyDefinitionTypeEnum.Group,
                    group_type_index: 1,
                },
                {
                    id: expect.any(String),
                    is_numerical: true,
                    name: 'numeric',
                    property_type: 'Numeric',
                    property_type_format: null,
                    query_usage_30_day: null,
                    team_id: teamId,
                    volume_30_day: null,
                    type: PropertyDefinitionTypeEnum.Group,
                    group_type_index: 1,
                },
            ])
        })

        it('regression tests: handles group set properties being empty', async () => {
            // See details of the regression
            // [here](https://posthog.slack.com/archives/C0460J93NBU/p1676384802876269)
            //
            // We were essentially failing and throwing a Sentry error if the
            // group properties was no an object. This test would throw before
            // the fix.
            await groupTypeManager.insertGroupType(teamId, 'project', 0)
            await groupTypeManager.insertGroupType(teamId, 'organization', 1)

            await manager.updateEventNamesAndProperties(teamId, '$groupidentify', {
                $group_type: 'organization',
                $group_key: 'org::5',
                $group_set: null,
            })
        })

        it('regression tests: handles group type property being empty', async () => {
            await groupTypeManager.insertGroupType(teamId, 'project', 0)
            await groupTypeManager.insertGroupType(teamId, 'organization', 1)

            await manager.updateEventNamesAndProperties(teamId, '$groupidentify', {
                $group_key: 'org::5',
                $group_set: {
                    foo: 'bar',
                    numeric: 3,
                },
            })
        })

        it('regression tests: 400 characters fit in property definitions', async () => {
            await groupTypeManager.insertGroupType(teamId, 'project', 0)
            await groupTypeManager.insertGroupType(teamId, 'organization', 1)

            const fourHundredSmileys = '😀'.repeat(400)
            const properties = {}
            properties[fourHundredSmileys] = 'foo'
            await manager.updateEventNamesAndProperties(teamId, fourHundredSmileys, properties)

            expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                expect.objectContaining({
                    id: expect.any(String),
                    team_id: teamId,
                    name: fourHundredSmileys,
                    is_numerical: false,
                    property_type: 'String',
                }),
            ])
        })

        it('regression tests: >400 characters are ignored in property definitions', async () => {
            await groupTypeManager.insertGroupType(teamId, 'project', 0)
            await groupTypeManager.insertGroupType(teamId, 'organization', 1)

            const fourHundredAndOneSmileys = '😀'.repeat(401)
            const properties = {}
            properties[fourHundredAndOneSmileys] = 'foo'

            // Note that this shouldn't throw, the large values are just skipped.
            await manager.updateEventNamesAndProperties(teamId, fourHundredAndOneSmileys, properties)

            expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([])
        })

        describe('auto-detection of property types', () => {
            const randomInteger = () => Math.floor(Math.random() * 1000) + 1
            const randomString = () => [...Array(10)].map(() => (~~(Math.random() * 36)).toString(36)).join('')

            it('adds no type for objects', async () => {
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    anObjectProperty: { anything: randomInteger() },
                })

                expect(manager.propertyDefinitionsCache.get(teamId)?.peek('1anObjectProperty')).toEqual(
                    NULL_AFTER_PROPERTY_TYPE_DETECTION
                )

                expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                    expect.objectContaining({
                        id: expect.any(String),
                        team_id: teamId,
                        name: 'anObjectProperty',
                        is_numerical: false,
                        property_type: null,
                    }),
                ])
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
                    await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                        some_bool: testcase,
                    })

                    expect(manager.propertyDefinitionsCache.get(teamId)?.peek('1some_bool')).toEqual('Boolean')

                    expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                        expect.objectContaining({
                            id: expect.any(String),
                            team_id: teamId,
                            name: 'some_bool',
                            is_numerical: false,
                            property_type: 'Boolean',
                        }),
                    ])
                })
            })

            // i.e. not using truthiness to detect whether something is boolean
            const notBoolTestCases = [0, 1, '0', '1', 'yes', 'no', null, undefined, '', [], ' ']
            notBoolTestCases.forEach((testcase) => {
                it(`does not identify ${testcase} as a boolean`, async () => {
                    await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                        some_bool: testcase,
                    })

                    expect(manager.propertyDefinitionsCache.get(teamId)?.peek('1some_bool')).not.toEqual('Boolean')
                })
            })

            it('identifies a numeric type', async () => {
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    some_number: randomInteger(),
                })

                expect(manager.propertyDefinitionsCache.get(teamId)?.peek('1some_number')).toEqual('Numeric')

                expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                    expect.objectContaining({
                        id: expect.any(String),
                        team_id: teamId,
                        name: 'some_number',
                        is_numerical: true,
                        property_type: 'Numeric',
                    }),
                ])
            })

            it('identifies a numeric type sent as a string... as a string', async () => {
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    some_number: String(randomInteger()),
                })

                expect(manager.propertyDefinitionsCache.get(teamId)?.peek('1some_number')).toEqual('String')

                expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                    expect.objectContaining({
                        id: expect.any(String),
                        team_id: teamId,
                        name: 'some_number',
                        property_type: 'String',
                    }),
                ])
            })

            it('identifies a string type', async () => {
                await manager.updateEventNamesAndProperties(teamId, 'another_test_event', {
                    some_string: randomString(),
                })

                expect(manager.propertyDefinitionsCache.get(teamId)?.peek('1some_string')).toEqual('String')

                expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                    expect.objectContaining({
                        id: expect.any(String),
                        team_id: teamId,
                        name: 'some_string',
                        is_numerical: false,
                        property_type: 'String',
                    }),
                ])
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
                    expectedPropertyType: PropertyType.String,
                },
                {
                    propertyKey: 'unix timestamp with five decimal places of fractional seconds as a string',
                    date: '1234567890.12345',
                    expectedPropertyType: PropertyType.String,
                },
                {
                    propertyKey: 'unix timestamp as a string',
                    date: '1234567890',
                    expectedPropertyType: PropertyType.String,
                },
                {
                    propertyKey: 'unix timestamp in milliseconds as a number',
                    date: 1234567890123,
                    expectedPropertyType: PropertyType.DateTime,
                },
                {
                    propertyKey: 'unix timestamp in milliseconds as a string',
                    date: '1234567890123',
                    expectedPropertyType: PropertyType.String,
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
                    expectedPropertyType: typeof toEdit.date === 'number' ? PropertyType.Numeric : PropertyType.String,
                }

                return [testcase, toMatchWithJustTimeInName, toNotMatch]
            })

            unixTimestampTestCases.forEach((testcase) => {
                it(`with key ${testcase.propertyKey} matches ${testcase.date} as ${testcase.expectedPropertyType}`, async () => {
                    const properties: Record<string, string | number> = {}
                    properties[testcase.propertyKey] = testcase.date
                    await manager.updateEventNamesAndProperties(teamId, 'another_test_event', properties)

                    expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                        expect.objectContaining({
                            id: expect.any(String),
                            team_id: teamId,
                            name: testcase.propertyKey,
                            is_numerical: testcase.expectedPropertyType === PropertyType.Numeric,
                            property_type: testcase.expectedPropertyType,
                        }),
                    ])
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
                    await manager.updateEventNamesAndProperties(teamId, 'another_test_event', properties)

                    expect(await hub.db.fetchPropertyDefinitions(teamId)).toEqual([
                        expect.objectContaining({
                            id: expect.any(String),
                            team_id: teamId,
                            name: testcase.propertyKey,
                            is_numerical: false,
                            property_type: PropertyType.DateTime,
                        }),
                    ])
                })
            })

            it('does identify type if the property was previously saved with no type', async () => {
                await manager.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'INSERT INTO posthog_propertydefinition (id, name, type, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type) VALUES ($1, $2, $3, $4, NULL, NULL, $5, $6)',
                    [new UUIDT().toString(), 'a_timestamp', PropertyDefinitionTypeEnum.Event, false, teamId, null],
                    'testTag'
                )

                await manager.updateEventNamesAndProperties(teamId, 'a_test_event', {
                    a_timestamp: 1234567890,
                })

                const results = await manager.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
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
                await manager.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'INSERT INTO posthog_propertydefinition (id, name, type, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type) VALUES ($1, $2, $3, $4, NULL, NULL, $5, $6)',
                    [
                        new UUIDT().toString(),
                        'a_prop_with_type',
                        PropertyDefinitionTypeEnum.Event,
                        false,
                        teamId,
                        PropertyType.DateTime,
                    ],
                    'testTag'
                )

                await manager.updateEventNamesAndProperties(teamId, 'a_test_event', {
                    a_prop_with_type: 1234567890,
                })

                const results = await manager.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
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
                const postgresQuery = jest.spyOn(hub.db.postgres, 'query')

                const properties = {
                    a_prop_with_a_type_we_do_not_set: { a: 1234567890 },
                }
                await manager.updateEventNamesAndProperties(teamId, 'a_test_event', properties)

                // 7 calls to DB to set up team manager and updateEventNamesAndProperties
                expect(postgresQuery.mock.calls).toHaveLength(7)

                await manager.updateEventNamesAndProperties(teamId, 'a_test_event', properties)

                // no more calls to DB as everything is cached
                expect(postgresQuery.mock.calls).toHaveLength(7)
            })
        })
    })
})
