import { KafkaMessage } from 'kafkajs'

import { formPluginEvent, normalizeEvent } from '../../src/utils/event'

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

        const event2 = { distinct_id: 'something', properties: { a: 1 } }
        expect(normalizeEvent(event2 as any).properties).toEqual({ a: 1 })
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
})

describe('formPluginEvent()', () => {
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

        expect(formPluginEvent(message)).toEqual({
            uuid: '01823e89-f75d-0000-0d4d-3d43e54f6de5',
            distinct_id: 'some_distinct_id',
            ip: null,
            site_url: 'http://example.com',
            team_id: 2,
            now: '2020-02-23T02:15:00Z',
            sent_at: '2020-02-23T02:15:00Z',
            event: 'some-event',
            properties: { foo: 123, $set: {}, $set_once: {} },
            timestamp: '2020-02-24T02:15:00Z',
            offset: 0,
            $set: {},
            $set_once: {},
        })
    })
})
