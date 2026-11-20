import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { dayjs } from 'lib/dayjs'

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
        change_request: null,
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

    describe('cron edits', () => {
        // The stored next run is Friday 13 Nov 12:00, and "now" is the day before.
        const fridayNoonSchedule: ScheduledChangeType = {
            ...scheduledChange,
            scheduled_at: '2026-11-13T12:00:00.000Z',
            end_date: null,
            cron_expression: '0 12 * * 5',
        }

        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2026-11-12T15:27:00.000Z'))
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone: 'UTC' })
            logic = featureFlagScheduleEditLogic({ id: 1 })
            logic.mount()
            logic.actions.openEdit(fridayNoonSchedule)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        test.each([
            ['an earlier time', ['0 11 * * 5'], '2026-11-13 11:00'],
            ['an extra weekday', ['0 12 * * 5,6'], '2026-11-13 12:00'],
            ['keystrokes that pass through another valid cron', ['0 1 * * 5', '0 13 * * 5'], '2026-11-13 13:00'],
        ])('editing the cron to %s keeps the first future match', (_, keystrokes, expectedNextRun) => {
            for (const cron of keystrokes) {
                logic.actions.setEditCronExpression(cron)
            }

            expect(logic.values.editScheduledAt?.format('YYYY-MM-DD HH:mm')).toBe(expectedNextRun)
        })

        test.each([
            ['a later day', 'UTC', '0 12 * * 5', '2026-11-20 09:00', '2026-11-20 12:00'],
            ['a match at midnight', 'UTC', '0 0 * * 5', '2026-11-20 09:00', '2026-11-20 00:00'],
            ['a past day', 'UTC', '0 12 * * 5', '2026-11-05 09:00', '2026-11-13 12:00'],
            // Without keepLocalTime the picked day would land 9 hours late and skip to 27 Nov
            ['a midnight match in Asia/Tokyo', 'Asia/Tokyo', '0 0 * * 5', '2026-11-20 09:00', '2026-11-20 00:00'],
        ])(
            'picking %s snaps to the first match on or after that day',
            (_, timezone, cron, pickedDay, expectedNextRun) => {
                initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })
                logic = featureFlagScheduleEditLogic({ id: 1 })
                logic.mount()
                logic.actions.openEdit(fridayNoonSchedule)

                const picked = dayjs(pickedDay)
                logic.actions.setEditScheduledAt(picked)
                logic.actions.setEditPickedDay(picked)
                logic.actions.setEditCronExpression(cron)

                expect(logic.values.editScheduledAt?.format('YYYY-MM-DD HH:mm')).toBe(expectedNextRun)
            }
        )

        test('typing the cron after picking a day keeps that day', () => {
            logic.actions.setEditPickedDay(dayjs('2026-12-04 09:00'))
            for (const cron of ['0 1 * * 5', '0 13 * * 5']) {
                logic.actions.setEditCronExpression(cron)
            }

            expect(logic.values.editScheduledAt?.format('YYYY-MM-DD HH:mm')).toBe('2026-12-04 13:00')
        })
    })
})
