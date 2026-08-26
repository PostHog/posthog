import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'
import { ScheduledChangeModels, ScheduledChangeOperationType, ScheduledChangeType, UserBasicType } from '~/types'

import { featureFlagScheduleEditLogic } from './featureFlagScheduleEditLogic'

describe('featureFlagScheduleEditLogic', () => {
    let logic: ReturnType<typeof featureFlagScheduleEditLogic.build>

    const scheduledChange: ScheduledChangeType = {
        id: 7,
        team_id: MOCK_DEFAULT_TEAM.id,
        record_id: 1,
        model_name: ScheduledChangeModels.FeatureFlag,
        payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: false },
        scheduled_at: '2026-06-15T14:30:00.000Z',
        end_date: '2026-06-30T23:59:59.999Z',
        executed_at: null,
        failure_reason: null,
        created_at: '2026-06-01T09:00:00.000Z',
        created_by: { id: 1, uuid: 'user-uuid', distinct_id: 'user-distinct-id' } as UserBasicType,
        is_recurring: true,
        recurrence_interval: null,
        cron_expression: '30 14 * * *',
        last_executed_at: null,
    }

    afterEach(() => {
        logic?.unmount()
    })

    // Guards the dispatch itself. The reducers that fill these dates must not read the store,
    // because Redux rejects a read while it dispatches and the dialog then never opens.
    test.each([
        ['UTC', '2026-06-15 14:30:00.000', '2026-06-30 23:59:59.999'],
        ['Asia/Tokyo', '2026-06-15 23:30:00.000', '2026-07-01 08:59:59.999'],
    ])(
        'openEdit fills the dialog with dates in the %s project timezone',
        (timezone, expectedScheduledAt, expectedEndDate) => {
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })
            logic = featureFlagScheduleEditLogic({ id: 1 })
            logic.mount()

            logic.actions.openEdit(scheduledChange)

            expect(logic.values.isEditOpen).toBe(true)
            expect(logic.values.editScheduledAt?.format('YYYY-MM-DD HH:mm:ss.SSS')).toBe(expectedScheduledAt)
            expect(logic.values.editEndDate?.format('YYYY-MM-DD HH:mm:ss.SSS')).toBe(expectedEndDate)
            expect(logic.values.editCronExpression).toBe('30 14 * * *')
            expect(logic.values.editPayloadValue).toBe(false)
        }
    )
})
