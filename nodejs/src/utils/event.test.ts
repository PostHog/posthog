import { DateTime } from 'luxon'

import { ClickHouseTimestamp, ProjectId, RawKafkaEvent } from '../types'
import { normalizeEvent, parseRawClickHouseEvent } from './event'

describe('normalizeEvent()', () => {
    describe('distinctId', () => {
        test.each([
            { distinctId: 'abc', expected: 'abc' },
            { distinctId: 123, expected: '123' },
            { distinctId: true, expected: 'true' },
        ])('$distinctId', ({ distinctId, expected }) => {
            const event = { distinct_id: distinctId }
            expect(normalizeEvent(event as any).distinct_id).toBe(expected)
        })
    })

    it('adds missing properties', () => {
        const event = { distinct_id: 'something' }
        expect(normalizeEvent(event as any).properties).toEqual({})

        const event2 = { distinct_id: 'something', properties: { a: 1 }, sent_at: '2020-02-23T02:15:00.000Z' }
        expect(normalizeEvent(event2 as any).properties).toEqual({ a: 1, $sent_at: '2020-02-23T02:15:00.000Z' })
    })

    it('combines .properties $set and $set_once with top-level $set and $set_once', () => {
        const event = {
            event: 'some_event',
            $set: { key1: 'value1', key2: 'value2' },
            $set_once: { key1_once: 'value1', key2_once: 'value2' },
            properties: {
                distinct_id: 'distinct_id1',
                $set: { key2: 'value3', key3: 'value4' },
                $set_once: { key2_once: 'value3', key3_once: 'value4' },
            },
        }
        const sanitized = normalizeEvent(event as any)

        expect(sanitized.properties!['$set']).toEqual({ key1: 'value1', key2: 'value2', key3: 'value4' })
        expect(sanitized.properties!['$set_once']).toEqual({
            key1_once: 'value1',
            key2_once: 'value2',
            key3_once: 'value4',
        })
    })

    it('sanitizes token', () => {
        const event = { token: '\u0000' }
        const sanitized = normalizeEvent(event as any)
        expect(sanitized.token).toBe('\uFFFD')
    })
})

describe('parseRawClickHouseEvent()', () => {
    it('parses a random event', () => {
        // @ts-expect-error TODO: Add missing `person_mode` field
        const kafkaEvent: RawKafkaEvent = {
            event: '$pageview',
            properties: JSON.stringify({
                $ip: '127.0.0.1',
            }),
            uuid: 'uuid1',
            elements_chain: '',
            timestamp: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
            team_id: 2,
            project_id: 1 as ProjectId,
            distinct_id: 'my_id',
            created_at: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
            person_created_at: '2020-02-23 02:10:00.00' as ClickHouseTimestamp,
            person_properties: JSON.stringify({ person_prop: 1 }),
            group0_properties: '',
            group1_properties: JSON.stringify({ a: 1, b: 2 }),
        }

        expect(parseRawClickHouseEvent(kafkaEvent)).toEqual({
            event: '$pageview',
            properties: {
                $ip: '127.0.0.1',
            },
            uuid: 'uuid1',
            timestamp: DateTime.fromISO('2020-02-23T02:15:00.000Z').toUTC(),
            team_id: 2,
            project_id: 1,
            distinct_id: 'my_id',
            created_at: DateTime.fromISO('2020-02-23T02:15:00.000Z').toUTC(),
            elements_chain: null,
            group0_properties: {},
            group1_properties: { a: 1, b: 2 },
            group2_properties: {},
            group3_properties: {},
            group4_properties: {},
            person_created_at: DateTime.fromISO('2020-02-23T02:10:00.000Z').toUTC(),
            person_properties: { person_prop: 1 },
            group0_created_at: null,
            group1_created_at: null,
            group2_created_at: null,
            group3_created_at: null,
            group4_created_at: null,
        })
    })
})
