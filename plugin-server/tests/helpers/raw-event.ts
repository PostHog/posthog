import { randomUUID } from 'crypto'

import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent, RawKafkaEvent } from '../../src/types'

/**
 * Helper function to create RawClickHouseEvent for tests with sensible defaults.
 *
 * @param overrides - Partial RawClickHouseEvent to override defaults
 * @returns Complete RawClickHouseEvent object
 *
 * @example
 * const event = createTestRawClickHouseEvent({
 *     team_id: 123,
 *     event: '$pageview',
 *     distinct_id: 'user-abc'
 * })
 */
export function createTestRawClickHouseEvent(overrides: Partial<RawClickHouseEvent> = {}): RawClickHouseEvent {
    const now = new Date().toISOString() as ClickHouseTimestamp
    return {
        uuid: randomUUID(),
        event: 'test_event',
        team_id: 1,
        project_id: 1 as ProjectId,
        distinct_id: 'test_distinct_id',
        timestamp: now,
        created_at: now,
        properties: '{}',
        elements_chain: '',
        person_created_at: now,
        person_properties: '{}',
        person_mode: 'full',
        historical_migration: false,
        ...overrides,
    }
}

/**
 * Helper function to create RawKafkaEvent for tests with sensible defaults.
 * RawKafkaEvent extends RawClickHouseEvent with a project_id field.
 *
 * @param overrides - Partial RawKafkaEvent to override defaults
 * @returns Complete RawKafkaEvent object
 */
export function createTestRawKafkaEvent(overrides: Partial<RawKafkaEvent> = {}): RawKafkaEvent {
    return {
        ...createTestRawClickHouseEvent(overrides),
        project_id: (overrides.project_id ?? overrides.team_id ?? 1) as ProjectId,
    }
}
