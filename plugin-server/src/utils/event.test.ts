import { DateTime } from 'luxon'

import { ClickHouseTimestamp, ProjectId, RawKafkaEvent } from '../types'
import { parseRawClickHouseEvent } from './event'

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
