import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { waitForExpect } from '~/tests/helpers/expectations'
import { resetKafka } from '~/tests/helpers/kafka'

import { Clickhouse } from '../../tests/helpers/clickhouse'
import { createUserTeamAndOrganization, fetchPostgresPersons, resetTestDatabase } from '../../tests/helpers/sql'
import { Hub, InternalPerson, PipelineEvent, PluginsServerConfig, ProjectId, RawClickHouseEvent, Team } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { parseRawClickHouseEvent } from '../utils/event'
import { parseJSON } from '../utils/json-parse'
import { UUIDT } from '../utils/utils'
import { fetchDistinctIds } from '../worker/ingestion/persons/repositories/test-helpers'
import { IngestionConsumer } from './ingestion-consumer'

// Mock the limiter so it always returns true
jest.mock('~/utils/token-bucket', () => {
    const mockConsume = jest.fn().mockReturnValue(true)
    return {
        IngestionWarningLimiter: {
            consume: mockConsume,
        },
    }
})

const waitForKafkaMessages = async (hub: Hub) => {
    await hub.db.kafkaProducer.flush()
}

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
        this.event.token = team.api_token
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

    withNow(now: number) {
        const date = DateTime.fromMillis(now)
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
    drop_events_older_than_seconds: null,
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
    config: { teamOverrides?: Partial<Team>; pluginServerConfig?: Partial<PluginsServerConfig> } = {},
    testFn: (ingester: IngestionConsumer, hub: Hub, team: Team) => Promise<void>
) => {
    test(name, async () => {
        const hub = await createHub({
            PLUGINS_DEFAULT_LOG_LEVEL: 0,
            APP_METRICS_FLUSH_FREQUENCY_MS: 0,
            ...config.pluginServerConfig,
        })

        const teamId = Math.floor((Date.now() % 1000000000) + Math.random() * 1000000)
        const userId = teamId
        const organizationId = new UUIDT().toString()

        const newTeam: Team = {
            ...DEFAULT_TEAM,
            id: teamId,
            project_id: teamId as ProjectId,
            organization_id: organizationId,
            uuid: v4(),
            name: teamId.toString(),
            ...config.teamOverrides,
        }
        const userUuid = new UUIDT().toString()
        const organizationMembershipId = new UUIDT().toString()

        await createUserTeamAndOrganization(
            hub.db.postgres,
            newTeam.id,
            userId,
            userUuid,
            newTeam.organization_id,
            organizationMembershipId,
            config.teamOverrides
        )

        // Fetch the team from the database to ensure we have the actual persisted data
        const fetchedTeam = await hub.teamManager.getTeam(newTeam.id)
        if (!fetchedTeam) {
            throw new Error(`Failed to fetch team ${newTeam.id} from database`)
        }

        const ingester = new IngestionConsumer(hub)
        // NOTE: We don't actually use kafka so we skip instantiation for faster tests
        ingester['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any

        jest.spyOn(hub.groupRepository, 'fetchGroup')
        jest.spyOn(hub.groupRepository, 'insertGroup')
        jest.spyOn(hub.groupRepository, 'updateGroup')
        jest.spyOn(hub.groupRepository, 'updateGroupOptimistically')

        await ingester.start()
        await testFn(ingester, hub, fetchedTeam)
        await ingester.stop()
        await closeHub(hub)
    })
}

describe('Event Pipeline E2E tests', () => {
    let clickhouse: Clickhouse
    beforeAll(async () => {
        console.log('Creating Clickhouse client')
        clickhouse = Clickhouse.create()
        await resetKafka()
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        process.env.SITE_URL = 'https://example.com'
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    testWithTeamIngester('should handle $$client_ingestion_warning events', {}, async (ingester, hub, team) => {
        const events = [
            new EventBuilder(team)
                .withEvent('$$client_ingestion_warning')
                .withProperties({ $$client_ingestion_warning_message: 'test message' })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            await waitForKafkaMessages(hub)
            const warnings = await fetchIngestionWarnings(hub, team.id)
            expect(warnings).toEqual([
                expect.objectContaining({
                    type: 'client_ingestion_warning',
                    team_id: team.id.toString(),
                    details: expect.objectContaining({ message: 'test message' }),
                }),
            ])
        })
    })

    testWithTeamIngester('should process events without a team_id', {}, async (ingester, hub, team) => {
        const events = [new EventBuilder(team).withEvent('test event').build()]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toBe(1)
            expect(events[0].team_id).toBe(team.id.toString())
        })
    })

    testWithTeamIngester(
        'can set and update group properties with $groupidentify events',
        {},
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

            await waitForKafkaMessages(hub)
            await waitForExpect(async () => {
                const group = await hub.groupRepository.fetchGroup(team.id, 0, groupKey)
                expect(group).toEqual(
                    expect.objectContaining({
                        team_id: team.id,
                        group_type_index: 0,
                        group_properties: { foo: 'bar' },
                        group_key: groupKey,
                        version: 1,
                    })
                )
            })

            const updateEvents = [
                new EventBuilder(team, distinctId)
                    .withEvent('$groupidentify')
                    .withGroupProperties('organization', groupKey, { prop: 'value' })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(updateEvents))

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const group = await hub.groupRepository.fetchGroup(team.id, 0, groupKey)
                expect(group).toEqual(
                    expect.objectContaining({
                        team_id: team.id,
                        group_type_index: 0,
                        group_properties: { foo: 'bar', prop: 'value' },
                        group_key: groupKey,
                        version: 2,
                    })
                )
            })

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(2)
                expect(events[0].event).toEqual('$groupidentify')
                expect(events[0].properties.$group_set).toEqual({ foo: 'bar' })
                expect(events[1].event).toEqual('$groupidentify')
                expect(events[1].properties.$group_set).toEqual({ prop: 'value' })
            })

            // Should have fetched the group 4 times:
            // 1 for each event and 2 in test check
            expect(hub.groupRepository.fetchGroup).toHaveBeenCalledTimes(4)
        }
    )

    testWithTeamIngester('can handle high amount of $groupidentify in same batch', {}, async (ingester, hub, team) => {
        const n = 150
        const distinctId = new UUIDT().toString()
        const events = []
        for (let i = 0; i < n; i++) {
            const m: Record<string, number> = {}
            m[i.toString()] = i
            events.push(
                new EventBuilder(team, distinctId)
                    .withEvent('$groupidentify')
                    .withGroupProperties('organization', 'group_key', m)
                    .build()
            )
        }

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(n)
        })

        expect(hub.groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(hub.groupRepository.insertGroup).toHaveBeenCalledTimes(1)
        expect(hub.groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(hub.groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)
    })

    testWithTeamIngester('can handle multiple $groupidentify in same batch', {}, async (ingester, hub, team) => {
        const timestamp = DateTime.now().toMillis()
        const distinctId = new UUIDT().toString()
        const groupKey = 'group_key'

        const events = [
            new EventBuilder(team, distinctId)
                .withEvent('$groupidentify')
                .withGroupProperties('organization', groupKey, { k1: 'v1' })
                .withTimestamp(timestamp)
                .build(),
            new EventBuilder(team, distinctId)
                .withEvent('$groupidentify')
                .withGroupProperties('organization', groupKey, { k2: 'v2', k3: 'v2' })
                .withTimestamp(timestamp + 1)
                .build(),
            new EventBuilder(team, distinctId)
                .withEvent('$groupidentify')
                .withGroupProperties('organization', groupKey, { k2: 'v3', k4: 'v3' })
                .withTimestamp(timestamp + 2)
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForExpect(async () => {
            await waitForKafkaMessages(hub)
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(3)
            expect(events[0].event).toEqual('$groupidentify')
            expect(events[0].properties.$group_set).toEqual({ k1: 'v1' })
            expect(events[1].event).toEqual('$groupidentify')
            expect(events[1].properties.$group_set).toEqual({ k2: 'v2', k3: 'v2' })
            expect(events[2].event).toEqual('$groupidentify')
            expect(events[2].properties.$group_set).toEqual({ k2: 'v3', k4: 'v3' })
        })

        expect(hub.groupRepository.fetchGroup).toHaveBeenCalledTimes(1)
        expect(hub.groupRepository.insertGroup).toHaveBeenCalledTimes(1)
        expect(hub.groupRepository.updateGroup).toHaveBeenCalledTimes(0)
        expect(hub.groupRepository.updateGroupOptimistically).toHaveBeenCalledTimes(1)

        await waitForExpect(async () => {
            const group = await hub.groupRepository.fetchGroup(team.id, 0, groupKey)
            expect(group).toEqual(
                expect.objectContaining({
                    team_id: team.id,
                    group_type_index: 0,
                    group_properties: { k1: 'v1', k2: 'v3', k3: 'v2', k4: 'v3' },
                    group_key: groupKey,
                    // Just one write after the creation of the group
                    version: 2,
                })
            )
        })
    })

    testWithTeamIngester('can handle $groupidentify with no properties', {}, async (ingester, hub, team) => {
        const events = [new EventBuilder(team).withEvent('$groupidentify').withProperties({}).build()]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(1)
            expect(events[0].event).toEqual('$groupidentify')
            expect(events[0].properties).toEqual({})
        })
    })

    testWithTeamIngester(
        'can handle multiple $groupidentify for different distinct ids',
        {},
        async (ingester, hub, team) => {
            const n = 50
            const distinctIds = []
            for (let i = 0; i < n; i++) {
                distinctIds.push(new UUIDT().toString())
            }

            const events = []
            for (const distinctId of distinctIds) {
                events.push(
                    new EventBuilder(team, distinctId)
                        .withEvent('$groupidentify')
                        .withGroupProperties('organization', distinctId, { foo: 'bar' })
                        .build()
                )
                events.push(
                    new EventBuilder(team, distinctId)
                        .withEvent('$groupidentify')
                        .withGroupProperties('organization', distinctId, { update: 'new' })
                        .build()
                )
            }

            // handle 100 events in one batch
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(n * 2)
            })

            for (const distinctId of distinctIds) {
                await waitForExpect(async () => {
                    const group = await hub.groupRepository.fetchGroup(team.id, 0, distinctId)
                    expect(group).toEqual(
                        expect.objectContaining({
                            team_id: team.id,
                            group_type_index: 0,
                            group_properties: { foo: 'bar', update: 'new' },
                            version: 2,
                        })
                    )
                })
            }
        }
    )

    testWithTeamIngester(
        'can handle multiple $groupidentify for different distinct ids',
        {},
        async (ingester, hub, team) => {
            const n = 50
            const distinctIds = []
            for (let i = 0; i < n; i++) {
                distinctIds.push(new UUIDT().toString())
            }

            const events = []
            for (const distinctId of distinctIds) {
                events.push(
                    new EventBuilder(team, distinctId)
                        .withEvent('$groupidentify')
                        .withGroupProperties('organization', distinctId, { foo: 'bar' })
                        .build()
                )
                events.push(
                    new EventBuilder(team, distinctId)
                        .withEvent('$groupidentify')
                        .withGroupProperties('organization', distinctId, { update: 'new' })
                        .build()
                )
            }

            // handle 100 events in one batch
            await ingester.handleKafkaBatch(createKafkaMessages(events))

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(n * 2)
            })

            for (const distinctId of distinctIds) {
                await waitForExpect(async () => {
                    const group = await hub.groupRepository.fetchGroup(team.id, 0, distinctId)
                    expect(group).toEqual(
                        expect.objectContaining({
                            team_id: team.id,
                            group_type_index: 0,
                            group_properties: { foo: 'bar', update: 'new' },
                            version: 2,
                        })
                    )
                })
            }
        }
    )

    testWithTeamIngester(
        'can $set and update person properties when reading event',
        {},
        async (ingester, hub, team) => {
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
            })
        }
    )

    testWithTeamIngester('can handle events with $process_person_profile=false', {}, async (ingester, hub, team) => {
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
        })
    })

    testWithTeamIngester(
        'force_upgrade triggers when personless event sent after person creation',
        {},
        async (ingester, hub, team) => {
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
                            $process_person_profile: false,
                        })
                        .withTimestamp(timestamp + 120000) // 2 minutes later (beyond 1-minute grace period)
                        .build(),
                ])
            )

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toEqual(2)
                expect(events[0].event).toEqual('$identify')
                expect(events[0].person_mode).toEqual('full')
                expect(events[1].event).toEqual('custom event')
                expect(events[1].person_mode).toEqual('force_upgrade')
                expect(events[1].person_properties).toEqual({})
            })
        }
    )

    testWithTeamIngester(
        'can $set and update person properties with top level $set',
        {},
        async (ingester, hub, team) => {
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
            })
        }
    )

    testWithTeamIngester(
        'should guarantee that person properties are set in the order of the events',
        {},
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
            })
        }
    )

    testWithTeamIngester(
        'should be able to $set_once person properties but not update',
        {},
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
            })
        }
    )

    testWithTeamIngester(
        'should be able to $set_once person properties but not update, at the top level',
        {},
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
            })
        }
    )

    testWithTeamIngester('should identify previous events with $anon_distinct_id', {}, async (ingester, hub, team) => {
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
        })
    })

    testWithTeamIngester('should perserve all events if merge fails', {}, async (ingester, hub, team) => {
        const illegalDistinctId = '0'
        const distinctId = new UUIDT().toString()

        const events = [
            new EventBuilder(team, illegalDistinctId).withEvent('custom event').withProperties({}).build(),
            new EventBuilder(team, distinctId).withEvent('custom event 2').withProperties({}).build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const persons = await fetchPersons(hub, team.id)
            expect(persons.length).toEqual(2)
        })

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
        })
    })

    testWithTeamIngester('should preserve properties if merge fails', {}, async (ingester, hub, team) => {
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
        })
    })

    testWithTeamIngester('should merge all events into same person id', {}, async (ingester, hub, team) => {
        const initialDistinctId = 'id1'
        const secondDistinctId = 'id2'
        const personIdentifier = 'person_id'

        const event1 = new EventBuilder(team, initialDistinctId).withEvent('custom event').withProperties({}).build()
        const event2 = new EventBuilder(team, secondDistinctId).withEvent('custom event 2').withProperties({}).build()

        await ingester.handleKafkaBatch(createKafkaMessages([event1, event2]))

        await waitForKafkaMessages(hub)

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
        })

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

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(4)
            // assert all events have the same person_id
            const personIds = new Set(events.map((event) => event.person_id))
            expect(personIds.size).toEqual(1)
        })
    })

    testWithTeamIngester('should resolve to same person id chained merges', {}, async (ingester, hub, team) => {
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

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(3)
            expect(new Set(events.map((event) => event.person_id)).size).toEqual(3)
        })

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

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toEqual(5)
            expect(new Set(events.map((event) => event.person_id)).size).toEqual(1)
        })
    })

    testWithTeamIngester(
        'should resolve to same person id even with complex chained merges',
        {},
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

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPersons(hub, team.id)
                expect(persons.length).toBe(4)
            })

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

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toBe(6)
            })

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

            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toBe(7)
                expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
            })
        }
    )

    testWithTeamIngester('should produce ingestion warnings for messages over 1MB', {}, async (ingester, hub, team) => {
        // For this we basically want the plugin-server to try and produce a new
        // message larger than 1MB. We do this by creating a person with a lot of
        // properties. We will end up denormalizing the person properties onto the
        // event, which already has the properties as $set therefore resulting in a
        // message that's larger than 1MB. There may also be other attributes that
        // are added to the event which pushes it over the limit.
        //
        // We verify that this is handled by checking that there is a message in the
        // appropriate topic.
        const distinctId = new UUIDT().toString()

        const personProperties = {
            distinct_id: distinctId,
            $set: {} as Record<string, string>,
        }

        for (let i = 0; i < 10000; i++) {
            personProperties.$set[new UUIDT().toString()] = new UUIDT().toString()
        }

        const events = [
            new EventBuilder(team, distinctId).withEvent('$identify').withProperties(personProperties).build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))

        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const ingestionWarnings = await fetchIngestionWarnings(hub, team.id)
            expect(ingestionWarnings.length).toBe(1)
            expect(ingestionWarnings[0].details.eventUuid).toBe(events[0].uuid)
        })
    })

    const fetchPersons = async (hub: Hub, teamId: number) => {
        const persons = await clickhouse.fetchPersons(teamId)
        return persons.map((person) => ({
            ...person,
            properties: parseJSON(person.properties),
        }))
    }

    const fetchEvents = async (hub: Hub, teamId: number) => {
        // Force ClickHouse to merge parts to ensure FINAL consistency with retry logic
        await retryClickHouseOperation(
            () => clickhouse.exec(`OPTIMIZE TABLE person_distinct_id_overrides FINAL`),
            'OPTIMIZE TABLE person_distinct_id_overrides FINAL',
            3, // max retries
            false // non-fatal operation
        )

        // Query events with retry logic for connection stability
        const queryResult = (await retryClickHouseOperation(
            () =>
                clickhouse.query(`
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
            `),
            'fetchEvents query',
            3, // max retries
            true // fatal operation
        )) as unknown as RawClickHouseEvent[]

        return queryResult.map(parseRawClickHouseEvent)
    }

    // Utility function for retrying ClickHouse operations with exponential backoff
    const retryClickHouseOperation = async <T>(
        operation: () => Promise<T>,
        operationName: string,
        maxRetries: number = 3,
        throwOnFailure: boolean = true
    ): Promise<T | null> => {
        let lastError: Error | null = null

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                return await operation()
            } catch (error: any) {
                lastError = error

                const isSocketError =
                    error?.message?.includes('socket hang up') ||
                    error?.message?.includes('ECONNRESET') ||
                    error?.message?.includes('ETIMEDOUT')

                if (isSocketError && attempt < maxRetries) {
                    const backoffMs = Math.min(1000 * Math.pow(2, attempt - 1), 10000) // Exponential backoff, max 10s
                    console.warn(
                        `[DEBUG] ClickHouse ${operationName} failed (attempt ${attempt}/${maxRetries}), retrying in ${backoffMs}ms:`,
                        error?.message
                    )
                    await new Promise((resolve) => setTimeout(resolve, backoffMs))
                    continue
                }

                console.warn(
                    `[DEBUG] ClickHouse ${operationName} failed (attempt ${attempt}/${maxRetries}):`,
                    error?.message
                )
                break
            }
        }

        if (throwOnFailure && lastError) {
            throw lastError
        } else if (lastError) {
            console.warn(
                `[DEBUG] ClickHouse ${operationName} failed after all retries (non-fatal):`,
                lastError?.message
            )
            return null
        }

        return null
    }

    const fetchIngestionWarnings = async (hub: Hub, teamId: number) => {
        const queryResult = (await retryClickHouseOperation(
            () =>
                clickhouse.query(`
                SELECT *
                FROM ingestion_warnings
                WHERE team_id = ${teamId}
            `),
            'fetchIngestionWarnings query',
            3, // max retries
            true // fatal operation
        )) as any[]

        return queryResult.map((warning: any) => ({ ...warning, details: parseJSON(warning.details) }))
    }

    testWithTeamIngester('alias events ordering scenario 1: original order', {}, async (ingester, hub, team) => {
        const testName = DateTime.now().toFormat('yyyy-MM-dd-HH-mm-ss')
        const user1DistinctId = 'user1-distinct-id'
        const user2DistinctId = 'user2-distinct-id'
        const user3DistinctId = 'user3-distinct-id'

        const events = [
            // User 1 creation
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        name: 'User 1',
                        email: `user1-${user1DistinctId}@example.com`,
                        age: 30,
                        test_name: testName,
                    },
                })
                .build(),
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        new_name: 'User 1 - Updated',
                    },
                })
                .build(),
            // User 2 creation
            new EventBuilder(team, user2DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        name: 'User 2',
                        email: `user2-${user2DistinctId}@example.com`,
                        age: 30,
                        test_name: testName,
                    },
                })
                .build(),
            new EventBuilder(team, user2DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        new_name: 'User 2 - Updated',
                    },
                })
                .build(),
            // Merge users: alias user1 -> user2
            new EventBuilder(team, user1DistinctId)
                .withEvent('$create_alias')
                .withProperties({
                    distinct_id: user1DistinctId,
                    alias: user2DistinctId,
                })
                .build(),

            // Create alias for user2 -> user3
            new EventBuilder(team, user2DistinctId)
                .withEvent('$create_alias')
                .withProperties({
                    distinct_id: user2DistinctId,
                    alias: user3DistinctId,
                })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))
        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toBe(6)

            // TODO: Add specific assertions based on expected behavior
            // All events should be processed without errors
            expect(events).toBeDefined()
        })

        // fetch the person properties
        await waitForExpect(async () => {
            const persons = await fetchPostgresPersons(hub.db, team.id)
            expect(persons.length).toBe(1)
            const personsClickhouse = await fetchPersons(hub, team.id)
            expect(personsClickhouse.length).toBe(1)
            expect(persons[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                    new_name: 'User 1 - Updated',
                    email: `user1-${user1DistinctId}@example.com`,
                    age: 30,
                    test_name: testName,
                })
            )
            expect(personsClickhouse[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                    new_name: 'User 1 - Updated',
                    email: `user1-${user1DistinctId}@example.com`,
                    age: 30,
                    test_name: testName,
                })
            )
            const distinctIdsPersons = await fetchDistinctIds(hub.db.postgres, {
                id: persons[0].id,
                team_id: team.id,
            } as InternalPerson)
            expect(distinctIdsPersons.length).toBe(3)
            // Except distinctids to match the ids, in any order
            expect(distinctIdsPersons.map((distinctId) => distinctId.distinct_id)).toEqual(
                expect.arrayContaining([user1DistinctId, user2DistinctId, user3DistinctId])
            )
        })
    })

    testWithTeamIngester('alias events ordering scenario 2: alias first', {}, async (ingester, hub, team) => {
        const testName = DateTime.now().toFormat('yyyy-MM-dd-HH-mm-ss')
        const user1DistinctId = 'user1-distinct-id'
        const user2DistinctId = 'user2-distinct-id'
        const user3DistinctId = 'user3-distinct-id'

        const events = [
            // User 1 creation
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        name: 'User 1',
                        email: `user1-${user1DistinctId}@example.com`,
                        age: 30,
                        test_name: testName,
                    },
                })
                .build(),
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        new_name: 'User 1 - Updated',
                    },
                })
                .build(),
            // User 2 creation
            new EventBuilder(team, user2DistinctId)
                .withProperties({
                    anon_distinct_id: user2DistinctId,
                    $set: {
                        name: 'User 2',
                        email: `user2-${user2DistinctId}@example.com`,
                        age: 30,
                        test_name: testName,
                    },
                })
                .build(),
            new EventBuilder(team, user2DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        new_name: 'User 2 - Updated',
                    },
                })
                .build(),

            // Create alias for user2 -> user3
            new EventBuilder(team, user2DistinctId)
                .withEvent('$create_alias')
                .withProperties({
                    distinct_id: user2DistinctId,
                    alias: user3DistinctId,
                })
                .build(),

            // Merge users: alias user1 -> user2
            new EventBuilder(team, user1DistinctId)
                .withEvent('$create_alias')
                .withProperties({
                    distinct_id: user1DistinctId,
                    alias: user2DistinctId,
                })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))
        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toBe(6)

            // TODO: Add specific assertions based on expected behavior
            // All events should be processed without errors
            expect(events).toBeDefined()
        })

        // fetch the person properties
        await waitForExpect(async () => {
            const persons = await fetchPostgresPersons(hub.db, team.id)
            expect(persons.length).toBe(1)
            const personsClickhouse = await fetchPersons(hub, team.id)
            expect(personsClickhouse.length).toBe(1)
            expect(persons[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                    new_name: 'User 1 - Updated',
                    email: `user1-${user1DistinctId}@example.com`,
                    age: 30,
                    test_name: testName,
                })
            )
            expect(personsClickhouse[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                    new_name: 'User 1 - Updated',
                    email: `user1-${user1DistinctId}@example.com`,
                    age: 30,
                    test_name: testName,
                })
            )
            const distinctIdsPersons = await fetchDistinctIds(hub.db.postgres, {
                id: persons[0].id,
                team_id: team.id,
            } as InternalPerson)
            expect(distinctIdsPersons.length).toBe(3)
            // Except distinctids to match the ids, in any order
            expect(distinctIdsPersons.map((distinctId) => distinctId.distinct_id)).toEqual(
                expect.arrayContaining([user1DistinctId, user2DistinctId, user3DistinctId])
            )
        })
    })

    testWithTeamIngester('alias events ordering scenario 2: user 2 first', {}, async (ingester, hub, team) => {
        const testName = DateTime.now().toFormat('yyyy-MM-dd-HH-mm-ss')
        const user1DistinctId = 'user1-distinct-id'
        const user2DistinctId = 'user2-distinct-id'
        const user3DistinctId = 'user3-distinct-id'

        const events = [
            // User 2 creation
            new EventBuilder(team, user2DistinctId)
                .withProperties({
                    anon_distinct_id: user2DistinctId,
                    $set: {
                        name: 'User 2',
                        email: `user2-${user2DistinctId}@example.com`,
                        age: 30,
                        test_name: testName,
                    },
                })
                .build(),
            new EventBuilder(team, user2DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        new_name: 'User 2 - Updated',
                    },
                })
                .build(),

            // Create alias for user2 -> user3
            new EventBuilder(team, user2DistinctId)
                .withEvent('$create_alias')
                .withProperties({
                    distinct_id: user2DistinctId,
                    alias: user3DistinctId,
                })
                .build(),

            // User 1 creation
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        name: 'User 1',
                        email: `user1-${user1DistinctId}@example.com`,
                        age: 30,
                        test_name: testName,
                    },
                })
                .build(),
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        new_name: 'User 1 - Updated',
                    },
                })
                .build(),

            // Merge users: alias user1 -> user2
            new EventBuilder(team, user1DistinctId)
                .withEvent('$create_alias')
                .withProperties({
                    distinct_id: user1DistinctId,
                    alias: user2DistinctId,
                })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))
        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toBe(6)

            // TODO: Add specific assertions based on expected behavior
            // All events should be processed without errors
            expect(events).toBeDefined()
        })

        // fetch the person properties
        await waitForExpect(async () => {
            const persons = await fetchPostgresPersons(hub.db, team.id)
            expect(persons.length).toBe(1)
            const personsClickhouse = await fetchPersons(hub, team.id)
            expect(personsClickhouse.length).toBe(1)
            expect(persons[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                    new_name: 'User 1 - Updated',
                    email: `user1-${user1DistinctId}@example.com`,
                    age: 30,
                    test_name: testName,
                })
            )
            expect(personsClickhouse[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                    new_name: 'User 1 - Updated',
                    email: `user1-${user1DistinctId}@example.com`,
                    age: 30,
                    test_name: testName,
                })
            )
            const distinctIdsPersons = await fetchDistinctIds(hub.db.postgres, {
                id: persons[0].id,
                team_id: team.id,
            } as InternalPerson)
            expect(distinctIdsPersons.length).toBe(3)
            // Except distinctids to match the ids, in any order
            expect(distinctIdsPersons.map((distinctId) => distinctId.distinct_id)).toEqual(
                expect.arrayContaining([user1DistinctId, user2DistinctId, user3DistinctId])
            )
        })
    })

    testWithTeamIngester(
        'alias events ordering scenario 2: user 2 first, separate batch',
        {},
        async (ingester, hub, team) => {
            const testName = DateTime.now().toFormat('yyyy-MM-dd-HH-mm-ss')
            const user1DistinctId = 'user1-distinct-id'
            const user2DistinctId = 'user2-distinct-id'
            const user3DistinctId = 'user3-distinct-id'

            const events = [
                // User 2 creation
                new EventBuilder(team, user2DistinctId)
                    .withProperties({
                        anon_distinct_id: user2DistinctId,
                        $set: {
                            name: 'User 2',
                            email: `user2-${user2DistinctId}@example.com`,
                            age: 30,
                            test_name: testName,
                        },
                    })
                    .build(),
                new EventBuilder(team, user2DistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: {
                            new_name: 'User 2 - Updated',
                        },
                    })
                    .build(),

                // Create alias for user2 -> user3
                new EventBuilder(team, user2DistinctId)
                    .withEvent('$create_alias')
                    .withProperties({
                        distinct_id: user2DistinctId,
                        alias: user3DistinctId,
                    })
                    .build(),
            ]

            const events2 = [
                // User 1 creation
                new EventBuilder(team, user1DistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: {
                            name: 'User 1',
                            email: `user1-${user1DistinctId}@example.com`,
                            age: 30,
                            test_name: testName,
                        },
                    })
                    .build(),
                new EventBuilder(team, user1DistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: {
                            new_name: 'User 1 - Updated',
                        },
                    })
                    .build(),

                // Merge users: alias user1 -> user2
                new EventBuilder(team, user1DistinctId)
                    .withEvent('$create_alias')
                    .withProperties({
                        distinct_id: user1DistinctId,
                        alias: user2DistinctId,
                    })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await ingester.handleKafkaBatch(createKafkaMessages(events2))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                expect(events.length).toBe(6)

                // TODO: Add specific assertions based on expected behavior
                // All events should be processed without errors
                expect(events).toBeDefined()
            })

            // fetch the person properties
            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.db, team.id)
                expect(persons.length).toBe(2)
                const personsClickhouse = await fetchPersons(hub, team.id)
                expect(personsClickhouse.length).toBe(2)
                expect(persons.map((person) => person.properties)).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            name: 'User 1',
                            new_name: 'User 1 - Updated',
                            email: `user1-${user1DistinctId}@example.com`,
                            age: 30,
                            test_name: testName,
                        }),
                        expect.objectContaining({
                            name: 'User 2',
                            new_name: 'User 2 - Updated',
                            email: `user2-${user2DistinctId}@example.com`,
                            age: 30,
                            test_name: testName,
                        }),
                    ])
                )
                expect(personsClickhouse.map((person) => person.properties)).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            name: 'User 1',
                            new_name: 'User 1 - Updated',
                            email: `user1-${user1DistinctId}@example.com`,
                            age: 30,
                            test_name: testName,
                        }),
                        expect.objectContaining({
                            name: 'User 2',
                            new_name: 'User 2 - Updated',
                            email: `user2-${user2DistinctId}@example.com`,
                            age: 30,
                            test_name: testName,
                        }),
                    ])
                )
                const person1 = persons.find((person) => person.properties.name === 'User 1')!
                const person2 = persons.find((person) => person.properties.name === 'User 2')!
                const distinctIdsPersons1 = await fetchDistinctIds(hub.db.postgres, {
                    id: person1.id,
                    team_id: team.id,
                } as InternalPerson)
                expect(distinctIdsPersons1.length).toBe(1)
                // Except distinctids to match the ids, in any order
                expect(distinctIdsPersons1.map((distinctId) => distinctId.distinct_id)).toEqual(
                    expect.arrayContaining([user1DistinctId])
                )
                const distinctIdsPersons2 = await fetchDistinctIds(hub.db.postgres, {
                    id: person2.id,
                    team_id: team.id,
                } as InternalPerson)
                expect(distinctIdsPersons2.length).toBe(2)
                // Except distinctids to match the ids, in any order
                expect(distinctIdsPersons2.map((distinctId) => distinctId.distinct_id)).toEqual(
                    expect.arrayContaining([user2DistinctId, user3DistinctId])
                )
            })
        }
    )

    testWithTeamIngester(
        'Should set and $unset person properties, different batches',
        {},
        async (ingester, hub, team) => {
            const user1DistinctId = 'user1-distinct-id'

            const events = [
                new EventBuilder(team, user1DistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $set: {
                            name: 'User 1',
                            property_to_unset: 'value',
                        },
                    })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.db, team.id)
                expect(persons.length).toBe(1)
                const personsClickhouse = await fetchPersons(hub, team.id)
                expect(personsClickhouse.length).toBe(1)
                expect(persons[0].properties).toMatchObject(
                    expect.objectContaining({
                        name: 'User 1',
                        property_to_unset: 'value',
                    })
                )
                expect(personsClickhouse[0].properties).toMatchObject(
                    expect.objectContaining({
                        name: 'User 1',
                        property_to_unset: 'value',
                    })
                )
            })

            const events2 = [
                new EventBuilder(team, user1DistinctId)
                    .withEvent('$identify')
                    .withProperties({
                        $unset: ['property_to_unset'],
                    })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events2))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.db, team.id)
                expect(persons.length).toBe(1)
                const personsClickhouse = await fetchPersons(hub, team.id)
                expect(personsClickhouse.length).toBe(1)
                expect(persons[0].properties).toMatchObject(
                    expect.objectContaining({
                        name: 'User 1',
                    })
                )
                expect(persons[0].properties).not.toHaveProperty('property_to_unset')
                expect(personsClickhouse[0].properties).toMatchObject(
                    expect.objectContaining({
                        name: 'User 1',
                    })
                )
                expect(personsClickhouse[0].properties).not.toHaveProperty('property_to_unset')
            })
        }
    )

    testWithTeamIngester('Should set and $unset person properties, same batch', {}, async (ingester, hub, team) => {
        const user1DistinctId = 'user1-distinct-id'

        const events = [
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $set: {
                        name: 'User 1',
                        property_to_unset: 'value',
                    },
                })
                .build(),
            new EventBuilder(team, user1DistinctId)
                .withEvent('$identify')
                .withProperties({
                    $unset: ['property_to_unset'],
                })
                .build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))
        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const persons = await fetchPostgresPersons(hub.db, team.id)
            expect(persons.length).toBe(1)
            const personsClickhouse = await fetchPersons(hub, team.id)
            expect(personsClickhouse.length).toBe(1)
            expect(persons[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                })
            )
            expect(persons[0].properties).not.toHaveProperty('property_to_unset')
            expect(personsClickhouse[0].properties).toMatchObject(
                expect.objectContaining({
                    name: 'User 1',
                })
            )
            expect(personsClickhouse[0].properties).not.toHaveProperty('property_to_unset')
        })
    })

    testWithTeamIngester(
        'should process events with various timestamps when dropping is disabled',
        { teamOverrides: { drop_events_older_than_seconds: null } },
        async (ingester, hub, team) => {
            const currentTime = DateTime.now().toMillis()
            const events = [
                // Current time event
                new EventBuilder(team)
                    .withEvent('current_time_event')
                    .withTimestamp(currentTime)
                    .withNow(currentTime)
                    .build(),
                // Recent event (30 minutes ago)
                new EventBuilder(team)
                    .withEvent('recent_event')
                    .withTimestamp(currentTime - 30 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Old event (2 hours ago)
                new EventBuilder(team)
                    .withEvent('old_event')
                    .withTimestamp(currentTime - 2 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Very old event (1 day ago)
                new EventBuilder(team)
                    .withEvent('very_old_event')
                    .withTimestamp(currentTime - 24 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Extremely old event (1 month ago)
                new EventBuilder(team)
                    .withEvent('extremely_old_event')
                    .withTimestamp(currentTime - 30 * 24 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Future event (1 hour from now)
                new EventBuilder(team)
                    .withEvent('future_event')
                    .withTimestamp(currentTime + 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                // All events should be processed when dropping is disabled
                expect(events.length).toBe(6)

                // Verify all events are present
                const eventTypes = events.map((e) => e.event)
                expect(eventTypes).toContain('current_time_event')
                expect(eventTypes).toContain('recent_event')
                expect(eventTypes).toContain('old_event')
                expect(eventTypes).toContain('very_old_event')
                expect(eventTypes).toContain('extremely_old_event')
                expect(eventTypes).toContain('future_event')
            })
        }
    )

    testWithTeamIngester(
        'should drop old events when dropping is enabled',
        { teamOverrides: { drop_events_older_than_seconds: 3600 } },
        async (ingester, hub, team) => {
            const currentTime = DateTime.now().toMillis()
            const events = [
                // Current time event - should pass
                new EventBuilder(team)
                    .withEvent('current_time_event')
                    .withTimestamp(currentTime)
                    .withNow(currentTime)
                    .build(),
                // Recent event (30 minutes ago) - should pass
                new EventBuilder(team)
                    .withEvent('recent_event')
                    .withTimestamp(currentTime - 30 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Just under threshold (59 minutes ago) - should pass
                new EventBuilder(team)
                    .withEvent('just_under_threshold')
                    .withTimestamp(currentTime - 59 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Just over threshold (61 minutes ago) - should be dropped
                new EventBuilder(team)
                    .withEvent('just_over_threshold')
                    .withTimestamp(currentTime - 61 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Old event (2 hours ago) - should be dropped
                new EventBuilder(team)
                    .withEvent('old_event')
                    .withTimestamp(currentTime - 2 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Very old event (1 day ago) - should be dropped
                new EventBuilder(team)
                    .withEvent('very_old_event')
                    .withTimestamp(currentTime - 24 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Future event (1 hour from now) - should pass
                new EventBuilder(team)
                    .withEvent('future_event')
                    .withTimestamp(currentTime + 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                // Only events under 1 hour old should be processed
                expect(events.length).toBe(4)

                // Verify only expected events are present
                const eventTypes = events.map((e) => e.event)
                expect(eventTypes).toContain('current_time_event')
                expect(eventTypes).toContain('recent_event')
                expect(eventTypes).toContain('just_under_threshold')
                expect(eventTypes).toContain('future_event')

                // Verify dropped events are not present
                expect(eventTypes).not.toContain('just_over_threshold')
                expect(eventTypes).not.toContain('old_event')
                expect(eventTypes).not.toContain('very_old_event')
            })

            // Check that ingestion warnings were created for dropped events
            await waitForExpect(async () => {
                const warnings = await fetchIngestionWarnings(hub, team.id)
                expect(warnings.length).toBe(3)

                const warningTypes = warnings.map((w) => w.type)
                expect(warningTypes).toEqual(
                    expect.arrayContaining(['event_dropped_too_old', 'event_dropped_too_old', 'event_dropped_too_old'])
                )
            })
        }
    )

    testWithTeamIngester(
        'should process all events when drop threshold is set to 0',
        { teamOverrides: { drop_events_older_than_seconds: 0 } },
        async (ingester, hub, team) => {
            const currentTime = DateTime.now().toMillis()
            const events = [
                // Current time event - should pass
                new EventBuilder(team)
                    .withEvent('current_time_event')
                    .withTimestamp(currentTime)
                    .withNow(currentTime)
                    .build(),
                // Recent event (30 minutes ago) - should pass
                new EventBuilder(team)
                    .withEvent('recent_event')
                    .withTimestamp(currentTime - 30 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Old event (2 hours ago) - should pass (0 threshold means no dropping)
                new EventBuilder(team)
                    .withEvent('old_event')
                    .withTimestamp(currentTime - 2 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Very old event (1 day ago) - should pass (0 threshold means no dropping)
                new EventBuilder(team)
                    .withEvent('very_old_event')
                    .withTimestamp(currentTime - 24 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Extremely old event (1 month ago) - should pass (0 threshold means no dropping)
                new EventBuilder(team)
                    .withEvent('extremely_old_event')
                    .withTimestamp(currentTime - 30 * 24 * 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
                // Future event (1 hour from now) - should pass
                new EventBuilder(team)
                    .withEvent('future_event')
                    .withTimestamp(currentTime + 60 * 60 * 1000)
                    .withNow(currentTime)
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const events = await fetchEvents(hub, team.id)
                // All events should be processed when threshold is 0 (no dropping)
                expect(events.length).toBe(6)

                // Verify all events are present
                const eventTypes = events.map((e) => e.event)
                expect(eventTypes).toContain('current_time_event')
                expect(eventTypes).toContain('recent_event')
                expect(eventTypes).toContain('old_event')
                expect(eventTypes).toContain('very_old_event')
                expect(eventTypes).toContain('extremely_old_event')
                expect(eventTypes).toContain('future_event')
            })

            // Check that no ingestion warnings were created (no events should be dropped)
            await waitForExpect(async () => {
                const warnings = await fetchIngestionWarnings(hub, team.id)
                expect(warnings.length).toBe(0)
            })
        }
    )

    // testWithTeamIngester(
    //     'we do not alias users if distinct id changes but we are already identified',
    //     {},
    //     async (ingester, hub, team) => {
    //         // This test is in reference to
    //         // https://github.com/PostHog/posthog/issues/5527 , where we were
    //         // correctly identifying that an anonymous user before login should be
    //         // aliased to the user they subsequently login as, but incorrectly
    //         // aliasing on subsequent $identify events. The anonymous case is
    //         // special as we want to alias to a known user, but otherwise we
    //         // shouldn't be doing so.

    //         const anonymousId = 'anonymous_id'
    //         const initialDistinctId = 'initial_distinct_id'
    //         const p2DistinctId = 'p2_distinct_id'
    //         const p2NewDistinctId = 'new_distinct_id'

    //         // Play out a sequence of events that should result in two users being
    //         // identified, with the first to events associated with one user, and
    //         // the third with another.
    //         const events = [
    //             new EventBuilder(team, anonymousId).withEvent('event 1').build(),
    //             new EventBuilder(team, initialDistinctId)
    //                 .withEvent('$identify')
    //                 .withProperties({ $anon_distinct_id: anonymousId })
    //                 .build(),
    //             new EventBuilder(team, initialDistinctId).withEvent('event 2').build(),
    //             new EventBuilder(team, p2DistinctId).withEvent('event 3').build(),
    //             new EventBuilder(team, p2NewDistinctId)
    //                 .withEvent('$identify')
    //                 .withProperties({ $anon_distinct_id: p2DistinctId })
    //                 .build(),
    //             new EventBuilder(team, p2NewDistinctId).withEvent('event 4').build(),
    //             // Let's also make sure that we do not alias when switching back to initialDistictId
    //             new EventBuilder(team, initialDistinctId)
    //                 .withEvent('$identify')
    //                 .withProperties({ $anon_distinct_id: p2NewDistinctId })
    //                 .build(),
    //         ]

    //         await ingester.handleKafkaBatch(createKafkaMessages(events))
    //         await waitForKafkaMessages(hub)

    //         await waitForExpect(async () => {
    //             const persons = await fetchPostgresPersons(hub.db, team.id)
    //             expect(persons.length).toBe(2)

    //             // Both persons should be identified
    //             expect(persons.map((person) => person.is_identified)).toEqual([true, true])

    //             // Check that events are grouped correctly by person
    //             const events = await fetchEvents(hub, team.id)
    //             const eventsByPersonId = new Map<string, string[]>()

    //             for (const event of events) {
    //                 const personId = event.person_id!
    //                 if (!eventsByPersonId.has(personId)) {
    //                     eventsByPersonId.set(personId, [])
    //                 }
    //                 eventsByPersonId.get(personId)!.push(event.event)
    //             }

    //             expect(eventsByPersonId.size).toBe(2)
    //             const eventGroups = Array.from(eventsByPersonId.values()).sort((a, b) => a.length - b.length)
    //             expect(eventGroups).toEqual(
    //                 expect.arrayContaining([
    //                     expect.arrayContaining(['event 3', '$identify', 'event 4']),
    //                     expect.arrayContaining(['event 1', '$identify', 'event 2', '$identify']),
    //                 ])
    //             )
    //         })
    //     }
    // )

    testWithTeamIngester(
        'we do not alias users if distinct id changes but we are already identified, with no anonymous event',
        {},
        async (ingester, hub, team) => {
            // This test is similar to the previous one, except it does not include an initial anonymous event.

            const anonymousId = 'anonymous_id'
            const initialDistinctId = 'initial_distinct_id'
            const p2DistinctId = 'p2_distinct_id'
            const p2NewDistinctId = 'new_distinct_id'

            // Play out a sequence of events that should result in two users being
            // identified, with the first to events associated with one user, and
            // the third with another.
            const events = [
                new EventBuilder(team, initialDistinctId)
                    .withEvent('$identify')
                    .withProperties({ $anon_distinct_id: anonymousId })
                    .build(),
                new EventBuilder(team, initialDistinctId).withEvent('event 2').build(),
                new EventBuilder(team, p2DistinctId).withEvent('event 3').build(),
                new EventBuilder(team, p2NewDistinctId)
                    .withEvent('$identify')
                    .withProperties({ $anon_distinct_id: p2DistinctId })
                    .build(),
                new EventBuilder(team, p2NewDistinctId).withEvent('event 4').build(),
                // Let's also make sure that we do not alias when switching back to initialDistictId
                new EventBuilder(team, initialDistinctId)
                    .withEvent('$identify')
                    .withProperties({ $anon_distinct_id: p2NewDistinctId })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.db, team.id)
                expect(persons.length).toBe(2)

                // Both persons should be identified
                expect(persons.map((person) => person.is_identified)).toEqual([true, true])

                // Check that events are grouped correctly by person
                const events = await fetchEvents(hub, team.id)
                const eventsByPersonId = new Map<string, string[]>()

                for (const event of events) {
                    const personId = event.person_id!
                    if (!eventsByPersonId.has(personId)) {
                        eventsByPersonId.set(personId, [])
                    }
                    eventsByPersonId.get(personId)!.push(event.event)
                }

                expect(eventsByPersonId.size).toBe(2)
                const eventGroups = Array.from(eventsByPersonId.values()).sort((a, b) => a.length - b.length)
                expect(eventGroups).toEqual(
                    expect.arrayContaining([
                        expect.arrayContaining(['event 3', '$identify', 'event 4']),
                        expect.arrayContaining(['$identify', 'event 2', '$identify']),
                    ])
                )
            })
        }
    )

    testWithTeamIngester(
        'we do not leave things in inconsistent state if $identify is run concurrently',
        {},
        async (ingester, hub, team) => {
            // There are a few places where we have the pattern of:
            //
            //  1. fetch from postgres
            //  2. check rows match condition
            //  3. perform update
            //
            // This test is designed to check the specific case where, in
            // handling we are creating an unidentified user, then updating this
            // user to have is_identified = true. Since we are using the
            // is_identified to decide on if we will merge persons, we want to
            // make sure we guard against this race condition.

            const anonymousId = 'anonymous_id'
            const initialDistinctId = 'initial-distinct-id'
            const newDistinctId = 'new-distinct-id'

            const events = [
                new EventBuilder(team, newDistinctId).withEvent('some event').build(),
                new EventBuilder(team, initialDistinctId)
                    .withEvent('$identify')
                    .withProperties({ $anon_distinct_id: anonymousId })
                    .build(),
                new EventBuilder(team, newDistinctId)
                    .withEvent('$identify')
                    .withProperties({ $anon_distinct_id: anonymousId })
                    .build(),
            ]

            await ingester.handleKafkaBatch(createKafkaMessages(events))
            await waitForKafkaMessages(hub)

            await waitForExpect(async () => {
                const persons = await fetchPostgresPersons(hub.db, team.id)
                expect(persons.length).toBe(2)
                expect(persons.map((person) => person.is_identified)).toEqual([true, true])
            })
        }
    )

    testWithTeamIngester('we can alias an anonymous person to an anonymous person', {}, async (ingester, hub, team) => {
        const anonymous1 = 'anonymous-1'
        const anonymous2 = 'anonymous-2'

        const events = [
            new EventBuilder(team, anonymous1).withEvent('anonymous event 1').build(),
            new EventBuilder(team, anonymous2).withEvent('anonymous event 2').build(),
            // Then try to alias them
            new EventBuilder(team, anonymous2).withEvent('$create_alias').withProperties({ alias: anonymous1 }).build(),
        ]

        await ingester.handleKafkaBatch(createKafkaMessages(events))
        await waitForKafkaMessages(hub)

        await waitForExpect(async () => {
            const persons = await fetchPostgresPersons(hub.db, team.id)
            expect(persons.length).toBe(1)

            // Make sure there is one identified person
            expect(persons.map((person) => person.is_identified)).toEqual([true])

            // Check that events are grouped correctly by person
            const events = await fetchEvents(hub, team.id)
            expect(events.length).toBe(3)

            // All events should belong to the same person
            const personIds = new Set(events.map((e) => e.person_id))
            expect(personIds.size).toBe(1)

            const eventNames = events.map((e) => e.event).sort()
            expect(eventNames).toEqual(['$create_alias', 'anonymous event 1', 'anonymous event 2'])
        })
    })
})
