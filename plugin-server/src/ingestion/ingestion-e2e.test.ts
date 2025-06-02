import ClickHouse from '@posthog/clickhouse'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { waitForExpect } from '~/tests/helpers/expectations'

import { resetTestDatabaseClickhouse } from '../../tests/helpers/clickhouse'
import { createUserTeamAndOrganization, resetTestDatabase } from '../../tests/helpers/sql'
import { Database, Hub, PipelineEvent, ProjectId, RawClickHouseEvent, Team } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { parseRawClickHouseEvent } from '../utils/event'
import { parseJSON } from '../utils/json-parse'
import { UUIDT } from '../utils/utils'
import { IngestionConsumer } from './ingestion-consumer'

class EventBuilder {
    private event: Partial<PipelineEvent> = {}

    constructor(team: Team, distinctId: string = new UUIDT().toString()) {
        this.event = {
            event: 'custom event',
            properties: {},
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }
        this.event.distinct_id = distinctId
        this.event.team_id = team.id
    }

    withEvent(event: string) {
        this.event.event = event
        return this
    }

    withProperties(properties: Record<string, any>) {
        this.event.properties = properties
        return this
    }

    withOverrides(overrides: Record<string, any>) {
        this.event = { ...this.event, ...overrides }
        return this
    }

    withTimestamp(timestamp: number) {
        const date = DateTime.fromMillis(timestamp)
        this.event.timestamp = date.toString()
        this.event.now = date.toString()
        return this
    }

    withGroupProperties(groupType: string, groupKey: string, groupSet?: Record<string, any>) {
        this.event.properties = {
            ...this.event.properties,
            $group_type: groupType,
            $group_key: groupKey,
            ...(groupSet ? { $group_set: groupSet } : {}),
        }
        return this
    }

    withToken(token: string) {
        this.event.token = token
        return this
    }

    build(): PipelineEvent {
        return this.event as PipelineEvent
    }
}

jest.mock('../utils/logger')

const DEFAULT_TEAM: Team = {
    id: 2,
    project_id: 2 as ProjectId,
    organization_id: '2',
    uuid: v4(),
    name: '2',
    anonymize_ips: true,
    api_token: 'api_token',
    slack_incoming_webhook: 'slack_incoming_webhook',
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
}

let offsetIncrementer = 0

const createKafkaMessage = (event: PipelineEvent, timestamp: number = DateTime.now().toMillis()): Message => {
    // TRICKY: This is the slightly different format that capture sends
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token: event.token,
        data: JSON.stringify(event),
    }
    return {
        key: `${event.token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: timestamp + offsetIncrementer,
        partition: 1,
    }
}

export const createKafkaMessages: (events: PipelineEvent[]) => Message[] = (events) => {
    return events.map(createKafkaMessage)
}

const testWithTeamIngester = (
    name: string,
    testFn: (ingester: IngestionConsumer, hub: Hub, team: Team) => Promise<void>,
    team: Team = DEFAULT_TEAM
) => {
    test.concurrent(name, async () => {
        const hub = await createHub({
            PLUGINS_DEFAULT_LOG_LEVEL: 0,
            APP_METRICS_FLUSH_FREQUENCY_MS: 0,
        })
        const teamId = Math.floor(Math.random() * 1000000000)
        const userId = teamId
        const organizationId = new UUIDT().toString()

        const newTeam: Team = {
            ...team,
            id: teamId,
            project_id: (team.project_id + 1) as ProjectId,
            organization_id: organizationId,
            uuid: v4(),
            name: (parseInt(team.name) + 1).toString(),
        }
        const userUuid = new UUIDT().toString()
        const organizationMembershipId = new UUIDT().toString()

        await createUserTeamAndOrganization(
            hub.db.postgres,
            newTeam.id,
            userId,
            userUuid,
            newTeam.organization_id,
            organizationMembershipId
        )
        const ingester = new IngestionConsumer(hub)
        // NOTE: We don't actually use kafka so we skip instantiation for faster tests
        ingester['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any
        await ingester.start()
        await testFn(ingester, hub, newTeam)
        await ingester.stop()
        await closeHub(hub)
    })
}

describe('Event Pipeline E2E tests', () => {
    beforeAll(async () => {
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
        process.env.SITE_URL = 'https://example.com'
    })

    testWithTeamIngester('should handle $$client_ingestion_warning events', async (ingester, hub, team) => {
        const events = [
            new EventBuilder(team)
                .withEvent('$$client_ingestion_warning')
                .withProperties({ $$client_ingestion_warning_message: 'test message' })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            await waitForExpect(async () => {
                const warnings = await fetchIngestionWarnings(hub, team.id)
                expect(warnings).toEqual([
                    expect.objectContaining({
                        type: 'client_ingestion_warning',
                        team_id: team.id,
                        details: expect.objectContaining({ message: 'test message' }),
                    }),
                ])
            })
        })
    })

    testWithTeamIngester('should process events without a team_id', async (ingester, hub, team) => {
        const token = team.api_token
        const events = [new EventBuilder(team).withEvent('test event').withToken(token).build()]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toBe(1)
            expect(events[0].team_id).toBe(team.id)
        })
    })

    testWithTeamIngester(
        'can set and update group properties with $groupidentify events',
        async (ingester, hub, team) => {
            const groupKey = 'group_key'
            const distinctId = new UUIDT().toString()

            const events = [
                new EventBuilder(team, distinctId)
                    .withEvent('$groupidentify')
                    .withGroupProperties('organization', groupKey, { foo: 'bar' })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))

            await waitForExpect(async () => {
                const group = await hub.db.fetchGroup(team.id, 0, groupKey)
                expect(group).toEqual(
                    expect.objectContaining({
                        team_id: team.id,
                        group_type_index: 0,
                        group_properties: { foo: 'bar' },
                        group_key: groupKey,
                        version: 1,
                    })
                )
            }, 5000)

            const updateEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$groupidentify')
                    .withGroupProperties('organization', groupKey, { prop: 'value' })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(updateEvents))

            await waitForExpect(async () => {
                const group = await hub.db.fetchGroup(team.id, 0, groupKey)
                expect(group).toEqual(
                    expect.objectContaining({
                        team_id: team.id,
                        group_type_index: 0,
                        group_properties: { foo: 'bar', prop: 'value' },
                        group_key: groupKey,
                        version: 2,
                    })
                )
            }, 5000)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(2)
                expect(events[0].event).toEqual('$groupidentify')
                expect(events[0].properties.$group_set).toEqual({ foo: 'bar' })
                expect(events[1].event).toEqual('$groupidentify')
                expect(events[1].properties.$group_set).toEqual({ prop: 'value' })
            }, 5000)
        }
    )

    testWithTeamIngester('can handle $groupidentify with no properties', async (ingester, hub, team) => {
        const events = [new EventBuilder(team).withEvent('$groupidentify').withProperties({}).build()]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(1)
            expect(events[0].event).toEqual('$groupidentify')
            expect(events[0].properties).toEqual({})
        }, 5000)
    })

    testWithTeamIngester('can $set and update person properties when reading event', async (ingester, hub, team) => {
        const distinctId = new UUIDT().toString()
        const timestamp = DateTime.now().toMillis()
        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { prop: 'value' },
                    })
                    .withTimestamp(timestamp)
                    .build(),
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { prop: 'updated value' },
                    })
                    .withTimestamp(timestamp + 1)
                    .build(),
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: { value: 'new value' },
                    })
                    .withTimestamp(timestamp + 2)
                    .build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(3)
            expect(events[0].event).toEqual('$identify')
            expect(events[0].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
            expect(events[1].event).toEqual('$identify')
            expect(events[1].person_properties).toEqual(expect.objectContaining({ prop: 'updated value' }))
            expect(events[2].event).toEqual('$identify')
            expect(events[2].person_properties).toEqual(
                expect.objectContaining({ prop: 'updated value', value: 'new value' })
            )
        }, 5000)
    })

    testWithTeamIngester('can handle events with $process_person_profile=false', async (ingester, hub, team) => {
        const distinctId = new UUIDT().toString()
        const timestamp = DateTime.now().toMillis()
        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        distinct_id: distinctId,
                        $set: { prop: 'value' },
                    })
                    .withTimestamp(timestamp)
                    .build(),
                new EventBuilder(team, distinctId)
                    .withEvent('custom event')
                    .withProperties({
                        distinctId: distinctId,
                        $process_person_profile: false,
                        $group_0: 'group_key',
                        $set: {
                            c: 3,
                        },
                        $set_once: {
                            d: 4,
                        },
                        $unset: ['prop'],
                    })
                    .withOverrides({
                        $set: {
                            a: 1,
                        },
                        $set_once: {
                            b: 2,
                        },
                    })
                    .withTimestamp(timestamp + 1)
                    .build(),
                new EventBuilder(team, distinctId)
                    .withEvent('custom event')
                    .withProperties({})
                    .withTimestamp(timestamp + 2)
                    .build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(3)
            expect(events[0].event).toEqual('$identify')
            expect(events[0].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
            expect(events[1].event).toEqual('custom event')
            expect(events[1].person_properties).toEqual({})
            expect(events[2].event).toEqual('custom event')
            expect(events[2].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
        }, 5000)
    })

    testWithTeamIngester('can $set and update person properties with top level $set', async (ingester, hub, team) => {
        const distinctId = new UUIDT().toString()
        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({
                        distinct_id: distinctId,
                    })
                    .withOverrides({
                        $set: { prop: 'value' },
                    })
                    .build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(1)
            expect(events[0].event).toEqual('$identify')
            expect(events[0].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
        }, 5000)
    })

    testWithTeamIngester(
        'should guarantee that person properties are set in the order of the events',
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const timestamp = DateTime.now().toMillis()

            const events = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({ $set: { prop: 'value' } })
                    .withTimestamp(timestamp)
                    .build(),

                new EventBuilder(team, distinctId)
                    .withEvent('custom event')
                    .withProperties({})
                    .withTimestamp(timestamp + 1)
                    .build(),

                new EventBuilder(team, distinctId)
                    .withEvent('custom event')
                    .withProperties({
                        $set: {
                            prop: 'updated value',
                            new_prop: 'new value',
                        },
                    })
                    .withTimestamp(timestamp + 2)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(3)
                expect(events[0].event).toEqual('$identify')
                expect(events[0].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
                expect(events[1].event).toEqual('custom event')
                expect(events[1].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
                expect(events[2].event).toEqual('custom event')
                expect(events[2].person_properties).toEqual(
                    expect.objectContaining({ prop: 'updated value', new_prop: 'new value' })
                )
            }, 5000)
        }
    )

    testWithTeamIngester(
        'should be able to $set_once person properties but not update',
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const events = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({ $set_once: { prop: 'value' } })
                    .build(),
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({ $set_once: { prop: 'updated value' } })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(2)
                expect(events[0].event).toEqual('$identify')
                expect(events[0].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
                expect(events[1].event).toEqual('$identify')
                expect(events[1].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
            }, 5000)
        }
    )

    testWithTeamIngester(
        'should be able to $set_once person properties but not update, at the top level',
        async (ingester, hub, team) => {
            const distinctId = new UUIDT().toString()
            const events = [
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({})
                    .withOverrides({ $set_once: { prop: 'value' } })
                    .build(),
                new EventBuilder(team, distinctId)
                    .withEvent('$identify')
                    .withProperties({})
                    .withOverrides({ $set_once: { prop: 'updated value' } })
                    .build(),
                new EventBuilder(team, distinctId).withEvent('custom event').withProperties({}).build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(3)
                expect(events[0].event).toEqual('$identify')
                expect(events[0].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
                expect(events[1].event).toEqual('$identify')
                expect(events[1].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
                expect(events[2].event).toEqual('custom event')
                expect(events[2].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
            }, 5000)
        }
    )

    testWithTeamIngester('should identify previous events with $anon_distinct_id', async (ingester, hub, team) => {
        const initialDistinctId = new UUIDT().toString()
        const personIdentifier = 'test@posthog.com'

        const events = [
            new EventBuilder(team, initialDistinctId).withEvent('custom event').withProperties({}).build(),
            new EventBuilder(team, personIdentifier)
                .withEvent('$identify')
                .withProperties({
                    distinct_id: personIdentifier,
                    $anon_distinct_id: initialDistinctId,
                })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(2)
            expect(events[0].person_id).toEqual(events[1].person_id)
        }, 5000)
    })

    testWithTeamIngester('should perserve all events if merge fails', async (ingester, hub, team) => {
        const illegalDistinctId = '0'
        const distinctId = new UUIDT().toString()

        const events = [
            new EventBuilder(team, illegalDistinctId).withEvent('custom event').withProperties({}).build(),
            new EventBuilder(team, distinctId).withEvent('custom event 2').withProperties({}).build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            const persons = await fetchPersons(hub, team.id)
            expect(persons.length).toEqual(2)
        }, 5000)

        const mergeEvents = [
            new EventBuilder(team, distinctId)
                .withEvent('$merge_dangerously')
                .withProperties({
                    distinct_id: distinctId,
                    alias: illegalDistinctId,
                    $set: { prop: 'value' },
                })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(mergeEvents))

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(3)
            // Assert that there are 2 different persons in person_id column
            const personIds = new Set(events.map((event) => event.person_id))
            expect(personIds.size).toEqual(2)
        }, 5000)
    })

    testWithTeamIngester('should preserve properties if merge fails', async (ingester, hub, team) => {
        const illegalDistinctId = '0'
        const distinctId = new UUIDT().toString()
        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, distinctId)
                    .withEvent('$merge_dangerously')
                    .withProperties({
                        distinct_id: distinctId,
                        alias: illegalDistinctId,
                        $set: { prop: 'value' },
                    })
                    .build(),
                new EventBuilder(team, distinctId).withEvent('custom event').withProperties({}).build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(2)
            expect(events[1].person_properties).toEqual(expect.objectContaining({ prop: 'value' }))
        }, 5000)
    })

    testWithTeamIngester('should merge all events into same person id', async (ingester, hub, team) => {
        const initialDistinctId = 'id1'
        const secondDistinctId = 'id2'
        const personIdentifier = 'person_id'

        const event1 = new EventBuilder(team, initialDistinctId).withEvent('custom event').withProperties({}).build()
        const event2 = new EventBuilder(team, secondDistinctId).withEvent('custom event 2').withProperties({}).build()

        await ingester.handleKafkaBatch(createKafkaMessages([event1, event2]))

        await waitForExpect(async () => {
            const persons = await fetchPersons(hub, team.id)
            expect(persons).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        properties: expect.objectContaining({
                            $creator_event_uuid: event1.uuid,
                        }),
                    }),
                    expect.objectContaining({
                        properties: expect.objectContaining({
                            $creator_event_uuid: event2.uuid,
                        }),
                    }),
                ])
            )
        }, 5000)

        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, personIdentifier)
                    .withEvent('$identify')
                    .withProperties({
                        distinct_id: personIdentifier,
                        $anon_distinct_id: initialDistinctId,
                    })
                    .build(),
                new EventBuilder(team, personIdentifier)
                    .withEvent('$identify')
                    .withProperties({
                        distinct_id: personIdentifier,
                        $anon_distinct_id: secondDistinctId,
                    })
                    .build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(4)
            // assert all events have the same person_id
            const personIds = new Set(events.map((event) => event.person_id))
            expect(personIds.size).toEqual(1)
        }, 5000)
    })

    testWithTeamIngester('should resolve to same person id chained merges', async (ingester, hub, team) => {
        const initialDistinctId = 'initialId'
        const secondDistinctId = 'secondId'
        const thirdDistinctId = 'thirdId'

        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, initialDistinctId).withEvent('custom event').withProperties({}).build(),
                new EventBuilder(team, secondDistinctId).withEvent('custom event 2').withProperties({}).build(),
                new EventBuilder(team, thirdDistinctId).withEvent('custom event 3').withProperties({}).build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(3)
            expect(new Set(events.map((event) => event.person_id)).size).toEqual(3)
        }, 5000)

        await ingester.handleKafkaBatch(
            createKafkaMessages([
                new EventBuilder(team, initialDistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        distinct_id: initialDistinctId,
                        $anon_distinct_id: secondDistinctId,
                    })
                    .build(),
                new EventBuilder(team, initialDistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        distinct_id: initialDistinctId,
                        $anon_distinct_id: thirdDistinctId,
                    })
                    .build(),
            ])
        )

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(5)
            expect(new Set(events.map((event) => event.person_id)).size).toEqual(1)
        }, 5000)
    })

    testWithTeamIngester(
        'should resolve to same person id even with complex chained merges',
        async (ingester, hub, team) => {
            const initialDistinctId = new UUIDT().toString()
            const secondDistinctId = new UUIDT().toString()
            const thirdDistinctId = new UUIDT().toString()
            const forthDistinctId = new UUIDT().toString()

            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, initialDistinctId).withEvent('custom event').withProperties({}).build(),
                    new EventBuilder(team, secondDistinctId).withEvent('custom event 2').withProperties({}).build(),
                    new EventBuilder(team, thirdDistinctId).withEvent('custom event 3').withProperties({}).build(),
                    new EventBuilder(team, forthDistinctId).withEvent('custom event 4').withProperties({}).build(),
                ])
            )

            await waitForExpect(async () => {
                const persons = await fetchPersons(hub, team.id)
                expect(persons.length).toBe(4)
            }, 5000)

            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, initialDistinctId)
                        .withEvent('$identify')
                        .withProperties({
                            distinct_id: initialDistinctId,
                            $anon_distinct_id: secondDistinctId,
                        })
                        .build(),
                    new EventBuilder(team, thirdDistinctId)
                        .withEvent('$identify')
                        .withProperties({
                            distinct_id: thirdDistinctId,
                            $anon_distinct_id: forthDistinctId,
                        })
                        .build(),
                ])
            )

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toBe(6)
            }, 5000)

            await ingester.handleKafkaBatch(
                createKafkaMessages([
                    new EventBuilder(team, secondDistinctId)
                        .withEvent('$merge_dangerously')
                        .withProperties({
                            distinct_id: secondDistinctId,
                            alias: thirdDistinctId,
                        })
                        .build(),
                ])
            )

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toBe(7)
                expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
            }, 5000)
        }
    )

    const fetchPersons = async (hub: Hub, teamId: number) => {
        const persons = await hub.db.fetchPersons(Database.ClickHouse, teamId)
        return persons.map((person) => ({
            ...person,
            properties: parseJSON(person.properties),
        }))
    }

    const fetchEvents = async (hub: Hub, teamId: number) => {
        const queryResult = (await hub.db.clickhouse.querying(`
            SELECT *,
                   if(notEmpty(overrides.person_id), overrides.person_id, e.person_id) as person_id
            FROM events e
            FINAL
            LEFT OUTER JOIN (
                SELECT
                    distinct_id,
                    argMax(person_id, version) as person_id
                  FROM person_distinct_id_overrides
                  FINAL
                  WHERE team_id = ${teamId}
                  GROUP BY distinct_id
            ) AS overrides USING distinct_id
            WHERE team_id = ${teamId}
            ORDER BY timestamp ASC
        `)) as unknown as ClickHouse.ObjectQueryResult<RawClickHouseEvent>
        return queryResult.data.map(parseRawClickHouseEvent)
    }

    const fetchIngestionWarnings = async (hub: Hub, teamId: number) => {
        const queryResult = (await hub.db.clickhouse.querying(`
            SELECT *
            FROM ingestion_warnings
            WHERE team_id = ${teamId}
            ORDER BY timestamp ASC
        `)) as unknown as ClickHouse.ObjectQueryResult<any>
        return queryResult.data.map((warning) => ({ ...warning, details: parseJSON(warning.details) }))
    }
})
