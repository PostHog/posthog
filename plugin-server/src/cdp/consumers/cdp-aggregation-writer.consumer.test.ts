import { resetCountersDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { defaultConfig } from '../../config/config'
import { Hub, Team } from '../../types'
import { AggregatedBehaviouralEvent, CdpAggregationWriterConsumer } from './cdp-aggregation-writer.consumer'
import { PersonEventPayload, ProducedEvent } from './cdp-behavioural-events.consumer'

jest.setTimeout(20_000)

describe('CdpAggregationWriterConsumer', () => {
    let processor: CdpAggregationWriterConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        // Create hub with explicit test counters database URL
        hub = await createHub({
            ...defaultConfig,
            COUNTERS_DATABASE_URL: 'postgres://posthog:posthog@localhost:5432/test_counters',
        })

        // Create a minimal team object for testing - we only need id and basic fields
        team = {
            id: 1,
            project_id: 1 as any,
            uuid: 'test-team-uuid',
            organization_id: 'test-org',
            name: 'Test Team',
        } as unknown as Team

        await resetCountersDatabase(hub.postgres)
        processor = new CdpAggregationWriterConsumer(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('CdpAggregationWriterConsumer', () => {
        it('should parse, deduplicate, aggregate, and write mixed events to database', async () => {
            const person1Id = '550e8400-e29b-41d4-a716-446655440000'
            const person2Id = '550e8400-e29b-41d4-a716-446655440001'

            // Create kafka messages with duplicates to test deduplication and aggregation
            const events: ProducedEvent[] = [
                // Person events with duplicates
                {
                    key: `${team.id}:${person1Id}:pageview`,
                    payload: {
                        type: 'person-performed-event',
                        personId: person1Id,
                        eventName: 'pageview',
                        teamId: team.id,
                    },
                },
                {
                    key: `${team.id}:${person1Id}:pageview`,
                    payload: {
                        type: 'person-performed-event',
                        personId: person1Id,
                        eventName: 'pageview',
                        teamId: team.id,
                    },
                }, // Duplicate - should be deduplicated
                {
                    key: `${team.id}:${person1Id}:click`,
                    payload: {
                        type: 'person-performed-event',
                        personId: person1Id,
                        eventName: 'click',
                        teamId: team.id,
                    },
                },
                // Behavioural events with duplicates
                {
                    key: `${team.id}:${person1Id}:hash123:2023-06-15`,
                    payload: {
                        type: 'behavioural-filter-match-event',
                        teamId: team.id,
                        personId: person1Id,
                        filterHash: 'hash123',
                        date: '2023-06-15',
                    },
                },
                {
                    key: `${team.id}:${person1Id}:hash123:2023-06-15`,
                    payload: {
                        type: 'behavioural-filter-match-event',
                        teamId: team.id,
                        personId: person1Id,
                        filterHash: 'hash123',
                        date: '2023-06-15',
                    },
                }, // Duplicate - should be aggregated
                {
                    key: `${team.id}:${person1Id}:hash123:2023-06-15`,
                    payload: {
                        type: 'behavioural-filter-match-event',
                        teamId: team.id,
                        personId: person1Id,
                        filterHash: 'hash123',
                        date: '2023-06-15',
                    },
                }, // Another duplicate - should be aggregated
                {
                    key: `${team.id}:${person2Id}:hash456:2023-06-15`,
                    payload: {
                        type: 'behavioural-filter-match-event',
                        teamId: team.id,
                        personId: person2Id,
                        filterHash: 'hash456',
                        date: '2023-06-15',
                    },
                },
            ]

            const messages = events.map((event) => ({
                value: Buffer.from(JSON.stringify(event)),
            })) as any[]

            // Parse the batch (this tests message parsing)
            const parsedBatch = await processor._parseKafkaBatch(messages)

            // Verify parsing worked correctly
            expect(parsedBatch.personPerformedEvents).toHaveLength(3) // Before deduplication
            expect(parsedBatch.behaviouralFilterMatchedEvents).toHaveLength(4) // Before aggregation

            // Process the batch (this tests deduplication, aggregation, and database writes)
            await processor['processBatch'](parsedBatch)

            // Verify person performed events in database (should be deduplicated)
            const personResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM person_performed_events WHERE team_id = $1 ORDER BY event_name',
                [team.id],
                'test-read-person-events'
            )

            expect(personResult.rows).toHaveLength(2) // Duplicates removed
            expect(personResult.rows[0]).toMatchObject({
                team_id: team.id,
                person_id: person1Id,
                event_name: 'click',
            })
            expect(personResult.rows[1]).toMatchObject({
                team_id: team.id,
                person_id: person1Id,
                event_name: 'pageview',
            })

            // Verify behavioural events in database (should be aggregated)
            const behaviouralResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM behavioural_filter_matched_events WHERE team_id = $1 ORDER BY filter_hash',
                [team.id],
                'test-read-behavioural-events'
            )

            expect(behaviouralResult.rows).toHaveLength(2) // One aggregated, one individual

            // First event (hash123) should have counter = 3 (from 3 duplicate events)
            expect(behaviouralResult.rows[0]).toMatchObject({
                team_id: team.id,
                person_id: person1Id,
                filter_hash: 'hash123',
                counter: 3,
            })
            expect(behaviouralResult.rows[0].date).toBeInstanceOf(Date)

            // Second event (hash456) should have counter = 1 (no duplicates)
            expect(behaviouralResult.rows[1]).toMatchObject({
                team_id: team.id,
                person_id: person2Id,
                filter_hash: 'hash456',
                counter: 1,
            })
            expect(behaviouralResult.rows[1].date).toBeInstanceOf(Date)
        })

        it('should handle empty batch gracefully', async () => {
            const parsedBatch = await processor._parseKafkaBatch([])
            expect(parsedBatch.personPerformedEvents).toHaveLength(0)
            expect(parsedBatch.behaviouralFilterMatchedEvents).toHaveLength(0)

            // Should not throw when processing empty batch
            await processor['processBatch'](parsedBatch)

            // Verify no records were written
            const personResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT COUNT(*) as count FROM person_performed_events WHERE team_id = $1',
                [team.id],
                'test-count-person-events'
            )
            expect(personResult.rows[0].count).toBe('0')

            const behaviouralResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT COUNT(*) as count FROM behavioural_filter_matched_events WHERE team_id = $1',
                [team.id],
                'test-count-behavioural-events'
            )
            expect(behaviouralResult.rows[0].count).toBe('0')
        })
        it('should handle upsert conflicts for behavioural events by incrementing counters', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const firstBatch: AggregatedBehaviouralEvent[] = [
                {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId,
                    filterHash: 'hash123',
                    date: '2023-01-01',
                    counter: 2,
                },
            ]

            const secondBatch: AggregatedBehaviouralEvent[] = [
                {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId,
                    filterHash: 'hash123',
                    date: '2023-01-01',
                    counter: 3,
                },
            ]

            // Write first batch
            await processor['writeToPostgres']([], firstBatch)
            // Write second batch (should update counter by adding values)
            await processor['writeToPostgres']([], secondBatch)

            // Verify the counter was incremented correctly
            const result = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM behavioural_filter_matched_events WHERE team_id = $1 AND filter_hash = $2',
                [team.id, 'hash123'],
                'test-read-upserted-events'
            )

            expect(result.rows).toHaveLength(1)
            expect(result.rows[0].counter).toBe(5) // 2 + 3
        })

        it('should handle upsert conflicts for person performed events by ignoring duplicates', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const events: PersonEventPayload[] = [
                {
                    type: 'person-performed-event',
                    personId,
                    eventName: 'pageview',
                    teamId: team.id,
                },
            ]

            // Write same event twice (should not duplicate)
            await processor['writeToPostgres'](events, [])
            await processor['writeToPostgres'](events, [])

            // Verify only one record exists
            const result = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM person_performed_events WHERE team_id = $1 AND person_id = $2 AND event_name = $3',
                [team.id, personId, 'pageview'],
                'test-read-duplicate-person-events'
            )
            expect(result.rows).toHaveLength(1)
        })

        it('should handle person events only (no behavioral events)', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const personEvents: PersonEventPayload[] = [
                {
                    type: 'person-performed-event',
                    personId,
                    eventName: 'signup',
                    teamId: team.id,
                },
                {
                    type: 'person-performed-event',
                    personId,
                    eventName: 'login',
                    teamId: team.id,
                },
            ]

            // Write only person events (no behavioral events)
            await processor['writeToPostgres'](personEvents, [])

            // Verify person events were written
            const personResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM person_performed_events WHERE team_id = $1 AND person_id = $2 ORDER BY event_name',
                [team.id, personId],
                'test-read-person-only-events'
            )
            expect(personResult.rows).toHaveLength(2)
            expect(personResult.rows[0].event_name).toBe('login')
            expect(personResult.rows[1].event_name).toBe('signup')

            // Verify no behavioral events were written
            const behavioralResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM behavioural_filter_matched_events WHERE team_id = $1',
                [team.id],
                'test-read-no-behavioral-events'
            )
            expect(behavioralResult.rows).toHaveLength(0)
        })

        it('should handle behavioral events only (no person events)', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const behavioralEvents: AggregatedBehaviouralEvent[] = [
                {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId,
                    filterHash: 'hash789',
                    date: '2023-12-01',
                    counter: 5,
                },
                {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId,
                    filterHash: 'hash456',
                    date: '2023-12-01',
                    counter: 2,
                },
            ]

            // Write only behavioral events (no person events)
            await processor['writeToPostgres']([], behavioralEvents)

            // Verify behavioral events were written
            const behavioralResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM behavioural_filter_matched_events WHERE team_id = $1 AND person_id = $2 ORDER BY filter_hash',
                [team.id, personId],
                'test-read-behavioral-only-events'
            )
            expect(behavioralResult.rows).toHaveLength(2)
            expect(behavioralResult.rows[0].filter_hash).toBe('hash456')
            expect(behavioralResult.rows[0].counter).toBe(2)
            expect(behavioralResult.rows[1].filter_hash).toBe('hash789')
            expect(behavioralResult.rows[1].counter).toBe(5)

            // Verify no person events were written
            const personResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM person_performed_events WHERE team_id = $1 AND person_id = $2',
                [team.id, personId],
                'test-read-no-person-events'
            )
            expect(personResult.rows).toHaveLength(0)
        })

        it('should clean null bytes and control characters that cause PostgreSQL errors', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440002'

            // Real-world example that caused "invalid byte sequence for encoding UTF8: 0x00"
            const personEvents: PersonEventPayload[] = [
                {
                    type: 'person-performed-event',
                    personId,
                    eventName: 'OpenApp\x00\x00\x00\x00\x04>-', // Contains null bytes like in the error
                    teamId: team.id,
                },
                {
                    type: 'person-performed-event',
                    personId,
                    eventName: 'event\x13with\x00control\x01chars', // Mix of control characters
                    teamId: team.id,
                },
            ]

            // Should NOT throw PostgreSQL protocol error
            await expect(processor['writeToPostgres'](personEvents, [])).resolves.not.toThrow()

            // Verify events were written with cleaned names
            const result = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT event_name FROM person_performed_events WHERE team_id = $1 AND person_id = $2 ORDER BY event_name',
                [team.id, personId],
                'test-read-cleaned-events'
            )

            expect(result.rows).toHaveLength(2)
            // sanitizeString replaces null bytes with � (replacement character)
            // Control character \x04 remains, null bytes become �
            expect(result.rows[0].event_name).toBe('OpenApp����\x04>-')
            // Control characters \x13 and \x01 remain, null byte becomes �
            expect(result.rows[1].event_name).toBe('event\x13with�control\x01chars')
        })

        it('should handle special characters that could cause PostgreSQL protocol errors', async () => {
            // These special characters previously caused "invalid message format" errors
            const validPersonId1 = '550e8400-e29b-41d4-a716-446655440002'
            const validPersonId2 = '550e8400-e29b-41d4-a716-446655440003'
            const problematicEventName = 'event\'with"quotes;and--comments/**/and\\backslash'
            const problematicFilterHash = "hash'with;semicolon--comment"

            const personEvents: PersonEventPayload[] = [
                {
                    type: 'person-performed-event',
                    personId: validPersonId1,
                    eventName: problematicEventName,
                    teamId: team.id,
                },
                {
                    type: 'person-performed-event',
                    personId: validPersonId2,
                    eventName: "event$with$dollars$and$1=1'); DROP TABLE person_performed_events; --", // SQL injection attempt
                    teamId: team.id,
                },
            ]

            const behavioralEvents: AggregatedBehaviouralEvent[] = [
                {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId: validPersonId1,
                    filterHash: problematicFilterHash,
                    date: '2023-12-01',
                    counter: 1,
                },
                {
                    type: 'behavioural-filter-match-event',
                    teamId: team.id,
                    personId: validPersonId2,
                    filterHash: "hash'); DELETE FROM behavioural_filter_matched_events_partitioned; --",
                    date: '2023-12-01',
                    counter: 1,
                },
            ]

            // This should NOT throw an error with parameterized queries
            await processor['writeToPostgres'](personEvents, behavioralEvents)

            // Verify person events were written correctly with special characters preserved
            const personResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM person_performed_events WHERE team_id = $1 ORDER BY event_name',
                [team.id],
                'test-read-special-char-person-events'
            )

            expect(personResult.rows).toHaveLength(2)
            expect(personResult.rows[0].event_name).toBe(
                "event$with$dollars$and$1=1'); DROP TABLE person_performed_events; --"
            )
            expect(personResult.rows[1].event_name).toBe(problematicEventName)
            expect(personResult.rows[1].person_id).toBe(validPersonId1)

            // Verify behavioral events were written correctly with special characters preserved
            const behavioralResult = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                'SELECT * FROM behavioural_filter_matched_events WHERE team_id = $1 ORDER BY person_id',
                [team.id],
                'test-read-special-char-behavioral-events'
            )

            expect(behavioralResult.rows).toHaveLength(2)
            expect(behavioralResult.rows[0].person_id).toBe(validPersonId1)
            expect(behavioralResult.rows[0].filter_hash).toBe(problematicFilterHash)
            expect(behavioralResult.rows[1].person_id).toBe(validPersonId2)
            expect(behavioralResult.rows[1].filter_hash).toBe(
                "hash'); DELETE FROM behavioural_filter_matched_events_partitioned; --"
            )

            // Verify tables still exist (SQL injection attempt failed)
            const tablesExist = await hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                `SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'behavioural_filter_matched_events'
                ) as table_exists`,
                [],
                'test-check-table-exists'
            )
            expect(tablesExist.rows[0].table_exists).toBe(true)
        })
    })
})
