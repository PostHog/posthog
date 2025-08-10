import { KafkaMessage } from 'kafkajs'
import { DateTime } from 'luxon'

import { ClickHouseTimestamp, ProjectId, RawKafkaEvent } from '../types'
import { formPipelineEvent, normalizeEvent, parseRawClickHouseEvent } from './event'

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

describe('formPipelineEvent()', () => {
    it('forms pluginEvent from a raw message', () => {
        const message = {
            value: Buffer.from(
                JSON.stringify({
                    uuid: '01823e89-f75d-0000-0d4d-3d43e54f6de5',
                    distinct_id: 'some_distinct_id',
                    ip: null,
                    site_url: 'http://example.com',
                    team_id: 2,
                    now: '2020-02-23T02:15:00Z',
                    sent_at: '2020-02-23T02:15:00Z',
                    token: 'phc_sometoken',
                    data: JSON.stringify({
                        event: 'some-event',
                        properties: { foo: 123 },
                        timestamp: '2020-02-24T02:15:00Z',
                        offset: 0,
                        $set: {},
                        $set_once: {},
                    }),
                })
            ),
        } as any as KafkaMessage

        // @ts-expect-error TODO: Fix type mismatches
        expect(formPipelineEvent(message)).toEqual({
            uuid: '01823e89-f75d-0000-0d4d-3d43e54f6de5',
            distinct_id: 'some_distinct_id',
            ip: null,
            site_url: 'http://example.com',
            team_id: 2,
            now: '2020-02-23T02:15:00Z',
            sent_at: '2020-02-23T02:15:00Z',
            token: 'phc_sometoken',
            event: 'some-event',
            properties: { foo: 123, $set: {}, $set_once: {}, $sent_at: '2020-02-23T02:15:00Z' },
            timestamp: '2020-02-24T02:15:00Z',
            offset: 0,
            $set: {},
            $set_once: {},
        })
    })

    it('does not override risky values', () => {
        const message = {
            value: Buffer.from(
                JSON.stringify({
                    uuid: '01823e89-f75d-0000-0d4d-3d43e54f6de5',
                    distinct_id: 'some_distinct_id',
                    ip: null,
                    site_url: 'http://example.com',
                    team_id: 2,
                    now: '2020-02-23T02:15:00Z',
                    sent_at: '2020-02-23T02:15:00Z',
                    token: 'phc_sometoken',
                    data: JSON.stringify({
                        // Risky overrides
                        uuid: 'bad-uuid',
                        distinct_id: 'bad long id',
                        ip: '192.168.0.1',
                        site_url: 'http://foo.com',
                        team_id: 456,
                        now: 'bad timestamp',
                        sent_at: 'bad timestamp',
                        // ...
                        event: 'some-event',
                        properties: { foo: 123 },
                        timestamp: '2020-02-24T02:15:00Z',
                        offset: 0,
                        $set: {},
                        $set_once: {},
                    }),
                })
            ),
        } as any as KafkaMessage

        // @ts-expect-error TODO: Fix type mismatches
        expect(formPipelineEvent(message)).toEqual({
            uuid: '01823e89-f75d-0000-0d4d-3d43e54f6de5',
            distinct_id: 'some_distinct_id',
            ip: null,
            site_url: 'http://example.com',
            team_id: 2,
            now: '2020-02-23T02:15:00Z',
            sent_at: '2020-02-23T02:15:00Z',
            token: 'phc_sometoken',
            event: 'some-event',
            properties: { foo: 123, $set: {}, $set_once: {}, $sent_at: '2020-02-23T02:15:00Z' },
            timestamp: '2020-02-24T02:15:00Z',
            offset: 0,
            $set: {},
            $set_once: {},
        })
    })
})
