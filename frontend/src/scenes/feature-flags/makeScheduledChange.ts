import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { ScheduledChangeModels, ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

let nextScheduledChangeId = 1

/** Reset the auto-incrementing id, for tests that rely on deterministic ids across cases. */
export function resetScheduledChangeIds(): void {
    nextScheduledChangeId = 1
}

/** Test and story factory: one home for the full ScheduledChangeType shape. */
export function makeScheduledChange(overrides: Partial<ScheduledChangeType> = {}): ScheduledChangeType {
    return {
        id: nextScheduledChangeId++,
        team_id: 1,
        record_id: 1,
        model_name: ScheduledChangeModels.FeatureFlag,
        payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: true },
        scheduled_at: '2030-01-01T00:00:00Z',
        executed_at: null,
        failure_reason: null,
        created_at: null,
        created_by: MOCK_DEFAULT_BASIC_USER,
        is_recurring: false,
        recurrence_interval: null,
        cron_expression: null,
        last_executed_at: null,
        end_date: null,
        change_request: null,
        ...overrides,
    }
}
