import { DateTime } from 'luxon'

import { Person } from '../../src/types'

export function createTestPerson(overrides: Partial<Person> = {}): Person {
    return {
        team_id: 1,
        properties: {},
        uuid: 'test-person-uuid',
        created_at: DateTime.utc(2023, 1, 1),
        ...overrides,
    }
}
