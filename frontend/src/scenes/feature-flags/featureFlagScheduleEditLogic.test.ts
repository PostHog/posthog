import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { ScheduledChangeModels, ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { featureFlagScheduleEditLogic } from './featureFlagScheduleEditLogic'

describe('featureFlagScheduleEditLogic', () => {
    let logic: ReturnType<typeof featureFlagScheduleEditLogic.build>

    const schedule: ScheduledChangeType = {
        id: 1,
        team_id: 1,
        record_id: 1,
        model_name: ScheduledChangeModels.FeatureFlag,
        payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: true },
        scheduled_at: '2026-08-10T12:00:00Z',
        executed_at: null,
        failure_reason: null,
        created_at: null,
        created_by: MOCK_DEFAULT_BASIC_USER,
        is_recurring: false,
        recurrence_interval: null,
        cron_expression: null,
        last_executed_at: null,
        end_date: null,
    }

    beforeEach(() => {
        // A non-UTC project timezone so timezone conversion is observable in assertions.
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone: 'America/Los_Angeles' })
        logic = featureFlagScheduleEditLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the edit dialog for a schedule with a scheduled_at without throwing', () => {
        expect(() => logic.actions.openEdit(schedule)).not.toThrow()

        expectLogic(logic).toMatchValues({
            isEditOpen: true,
            editingSchedule: schedule,
        })
        // The project is in America/Los_Angeles (PDT, UTC-7), so the stored 12:00Z surfaces as a
        // 05:00 wall clock. Asserting the exact time proves openEdit applied the project timezone
        // rather than silently falling back to UTC.
        expect(logic.values.editScheduledAt?.format('YYYY-MM-DD HH:mm')).toBe('2026-08-10 05:00')
    })

    it('converts end_date to the project timezone on open', () => {
        logic.actions.openEdit({ ...schedule, end_date: '2026-09-10T12:00:00Z' })
        // Same PDT (UTC-7) conversion as scheduled_at, exercising the separate end-date path.
        expect(logic.values.editEndDate?.format('YYYY-MM-DD HH:mm')).toBe('2026-09-10 05:00')
    })
})
