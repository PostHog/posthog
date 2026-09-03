import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { serializeEvent } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { ISOTimestamp, ProcessedEvent, ProjectId } from '~/types'

import { mapProcessedEventToFlagEvaluationRow } from './flag-evaluation-row'

describe('mapProcessedEventToFlagEvaluationRow', () => {
    const processedEvent: ProcessedEvent = {
        uuid: 'event-uuid-1',
        event: '$feature_flag_called',
        properties: { $feature_flag: 'my-flag', $feature_flag_response: true, $group_0: 'org-1' },
        timestamp: '2024-01-15T10:30:00.123Z' as ISOTimestamp,
        team_id: 42,
        project_id: 7 as ProjectId,
        distinct_id: 'distinct-1',
        elements_chain: '',
        created_at: DateTime.fromISO('2024-01-15T10:31:00.456Z'),
        captured_at: null,
        person_id: 'person-uuid-1',
        person_properties: { email: 'a@example.com' },
        person_created_at: DateTime.fromISO('2023-01-01T00:00:00.000Z'),
        person_mode: 'full',
    }

    it('narrows the events wire format to the flag_evaluations columns, byte-identical on shared fields', () => {
        const row = mapProcessedEventToFlagEvaluationRow(processedEvent)
        const eventsRow = serializeEvent(processedEvent)

        expect(row.uuid).toBe('event-uuid-1')
        expect(row.event).toBe('$feature_flag_called')
        expect(row.team_id).toBe(42)
        expect(row.distinct_id).toBe('distinct-1')
        expect(row.person_id).toBe('person-uuid-1')
        expect(row.timestamp).toBe('2024-01-15 10:30:00.123')
        expect(row.properties).toBe(eventsRow.properties)
        expect(row.person_properties).toBe(eventsRow.person_properties)
        // Both rows derive created_at from the event, so they agree. Reading the
        // wall clock per serialization instead would stamp two different values.
        expect(row.created_at).toBe(eventsRow.created_at)
        expect(row.created_at).toBe('2024-01-15 10:31:00.456')
        expect(parseJSON(row.properties!).$feature_flag).toBe('my-flag')
        expect(parseJSON(row.person_properties!).email).toBe('a@example.com')
    })

    it('emits exactly the kafka_flag_evaluations column set', () => {
        // An extra key (elements_chain, person_mode, a materialized column name)
        // is not a column on the Kafka table; keep the wire format in lockstep
        // with posthog/models/flag_evaluations/sql.py.
        const row = mapProcessedEventToFlagEvaluationRow(processedEvent)

        expect(Object.keys(row).sort()).toEqual([
            'created_at',
            'distinct_id',
            'event',
            'person_id',
            'person_properties',
            'properties',
            'team_id',
            'timestamp',
            'uuid',
        ])
    })
})
