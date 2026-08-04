import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { ScheduledChangeModels, ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { featureFlagScheduleEditLogic } from './featureFlagScheduleEditLogic'

describe('featureFlagScheduleEditLogic', () => {
    let logic: ReturnType<typeof featureFlagScheduleEditLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featureFlagScheduleEditLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the edit dialog for a schedule with a scheduled_at without throwing', () => {
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
            created_by: null as any,
            is_recurring: false,
            recurrence_interval: null,
            cron_expression: null,
            last_executed_at: null,
            end_date: null,
        }

        expect(() => logic.actions.openEdit(schedule, 'America/Los_Angeles')).not.toThrow()

        expectLogic(logic).toMatchValues({
            isEditOpen: true,
            editingSchedule: schedule,
        })
        expect(logic.values.editScheduledAt).not.toBeNull()
    })
})
