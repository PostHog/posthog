import { CronExpressionParser } from 'cron-parser'
import { actions, connect, key, kea, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { RecurrenceInterval, ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { teamLogic } from '../teamLogic'
import {
    describeCron,
    featureFlagLogic,
    scheduleDateFromStoredISO,
    scheduleDateToProjectTzISO,
} from './featureFlagLogic'
import type { featureFlagScheduleEditLogicType } from './featureFlagScheduleEditLogicType'

// Used from reducers, which don't receive `values` — we still need a synchronous read at
// action-dispatch time. Selectors and listeners use the reactive `projectTimezone` selector instead.
function projectTimezoneImperative(): string {
    return teamLogic.findMounted()?.values.currentTeam?.timezone || 'UTC'
}

export interface FeatureFlagScheduleEditLogicProps {
    id: number | 'new' | 'link'
}

export const featureFlagScheduleEditLogic = kea<featureFlagScheduleEditLogicType>([
    path((id) => ['scenes', 'feature-flags', 'featureFlagScheduleEditLogic', id]),
    props({} as FeatureFlagScheduleEditLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        openEdit: (schedule: ScheduledChangeType) => ({ schedule }),
        closeEdit: true,
        setEditScheduledAt: (date: Dayjs | null) => ({ date }),
        setEditCronExpression: (cron: string | null) => ({ cron }),
        setEditRecurrenceInterval: (interval: RecurrenceInterval | null) => ({ interval }),
        setEditEndDate: (date: Dayjs | null) => ({ date }),
        setEditIsRecurring: (isRecurring: boolean) => ({ isRecurring }),
        setEditPayloadValue: (value: boolean) => ({ value }),
        setEditRepeatsValue: (value: RecurrenceInterval | 'none' | 'cron') => ({ value }),
        saveEdit: true,
        saveEditSuccess: true,
        saveEditFailure: true,
    }),
    reducers({
        editingSchedule: [
            null as ScheduledChangeType | null,
            {
                openEdit: (_, { schedule }) => schedule,
                closeEdit: () => null,
                saveEditSuccess: () => null,
            },
        ],
        editScheduledAt: [
            null as Dayjs | null,
            {
                openEdit: (_, { schedule }) =>
                    schedule.scheduled_at
                        ? scheduleDateFromStoredISO(schedule.scheduled_at, projectTimezoneImperative())
                        : null,
                setEditScheduledAt: (_, { date }) => date,
                closeEdit: () => null,
            },
        ],
        editCronExpression: [
            null as string | null,
            {
                openEdit: (_, { schedule }) => schedule.cron_expression,
                setEditCronExpression: (_, { cron }) => cron,
                closeEdit: () => null,
            },
        ],
        editRecurrenceInterval: [
            null as RecurrenceInterval | null,
            {
                openEdit: (_, { schedule }) => schedule.recurrence_interval,
                setEditRecurrenceInterval: (_, { interval }) => interval,
                closeEdit: () => null,
            },
        ],
        editEndDate: [
            null as Dayjs | null,
            {
                openEdit: (_, { schedule }) =>
                    schedule.end_date
                        ? scheduleDateFromStoredISO(schedule.end_date, projectTimezoneImperative())
                        : null,
                setEditEndDate: (_, { date }) => date,
                closeEdit: () => null,
            },
        ],
        editIsRecurring: [
            false,
            {
                openEdit: (_, { schedule }) =>
                    schedule.is_recurring || !!schedule.recurrence_interval || !!schedule.cron_expression,
                setEditIsRecurring: (_, { isRecurring }) => isRecurring,
                closeEdit: () => false,
            },
        ],
        editPayloadValue: [
            true as boolean,
            {
                openEdit: (_, { schedule }) => {
                    if (schedule.payload.operation === ScheduledChangeOperationType.UpdateStatus) {
                        return schedule.payload.value
                    }
                    return true
                },
                setEditPayloadValue: (_, { value }) => value,
                closeEdit: () => true,
            },
        ],
        editSaving: [
            false,
            {
                saveEdit: () => true,
                saveEditSuccess: () => false,
                saveEditFailure: () => false,
            },
        ],
    }),
    selectors({
        isEditOpen: [(s) => [s.editingSchedule], (schedule): boolean => schedule !== null],
        // Reactive timezone input — selectors that depend on it recompute when the project
        // timezone changes, which matters if the user switches projects while the edit dialog is open.
        projectTimezone: [(s) => [s.currentTeam], (currentTeam): string => currentTeam?.timezone || 'UTC'],
        editRepeatsValue: [
            (s) => [s.editIsRecurring, s.editCronExpression, s.editRecurrenceInterval],
            (isRecurring, cron, interval): RecurrenceInterval | 'none' | 'cron' =>
                isRecurring ? (cron !== null ? 'cron' : (interval ?? 'none')) : 'none',
        ],
        editCronPreview: [(s) => [s.editCronExpression], (cron): string | null => describeCron(cron)],
        editOperationType: [
            (s) => [s.editingSchedule],
            (schedule): ScheduledChangeOperationType | null => schedule?.payload?.operation ?? null,
        ],
        hasEditChanges: [
            (s) => [
                s.editingSchedule,
                s.editScheduledAt,
                s.editCronExpression,
                s.editRecurrenceInterval,
                s.editEndDate,
                s.editIsRecurring,
                s.editPayloadValue,
                s.projectTimezone,
            ],
            (schedule, scheduledAt, cron, interval, endDate, isRecurring, payloadValue, tz): boolean => {
                if (!schedule) {
                    return false
                }
                const origScheduledAt = schedule.scheduled_at ? dayjs(schedule.scheduled_at).toISOString() : null
                const newScheduledAt = scheduledAt ? scheduleDateToProjectTzISO(scheduledAt, tz) : null
                if (origScheduledAt !== newScheduledAt) {
                    return true
                }
                if (schedule.cron_expression !== cron) {
                    return true
                }
                if (schedule.recurrence_interval !== interval) {
                    return true
                }
                const origEndDate = schedule.end_date ? dayjs(schedule.end_date).toISOString() : null
                const newEndDate = endDate ? endDate.tz(tz, true).endOf('day').toISOString() : null
                if (origEndDate !== newEndDate) {
                    return true
                }
                // For paused schedules the effective recurring state may differ
                const origIsRecurring =
                    schedule.is_recurring || !!schedule.recurrence_interval || !!schedule.cron_expression
                if (origIsRecurring !== isRecurring) {
                    return true
                }
                if (
                    schedule.payload.operation === ScheduledChangeOperationType.UpdateStatus &&
                    schedule.payload.value !== payloadValue
                ) {
                    return true
                }
                return false
            },
        ],
        editValidationErrors: [
            (s) => [s.editScheduledAt, s.editCronExpression, s.editEndDate, s.editIsRecurring, s.projectTimezone],
            (scheduledAt, cron, endDate, isRecurring, tz): Record<string, string> => {
                const errors: Record<string, string> = {}
                // editScheduledAt is a browser-local Dayjs whose wall clock mirrors the project
                // timezone, so we reinterpret it in project tz before comparing to "now".
                const scheduledAtInstant = scheduledAt ? scheduledAt.tz(tz, true) : null
                if (!scheduledAt) {
                    errors.scheduledAt = 'Scheduled date is required'
                } else if (!isRecurring && scheduledAtInstant!.isBefore(dayjs())) {
                    errors.scheduledAt = 'Scheduled date must be in the future'
                }
                if (cron) {
                    const fields = cron.trim().split(/\s+/)
                    if (fields.length !== 5) {
                        errors.cronExpression = 'Only 5-field cron expressions are supported'
                    } else {
                        try {
                            CronExpressionParser.parse(cron)
                        } catch {
                            errors.cronExpression = 'Invalid cron expression'
                        }
                    }
                } else if (isRecurring && cron !== null) {
                    // User is in cron mode (cron is '' rather than null) but hasn't entered an expression
                    errors.cronExpression = 'Enter a cron expression'
                }
                const normalizedEndDate = endDate ? endDate.tz(tz, true).endOf('day') : null
                if (normalizedEndDate && scheduledAtInstant && normalizedEndDate.isBefore(scheduledAtInstant)) {
                    errors.endDate = 'End date must be after the scheduled start date'
                }
                return errors
            },
        ],
    }),
    listeners(({ actions, values, props: logicProps }) => ({
        setEditRepeatsValue: ({ value }) => {
            if (value === 'none') {
                actions.setEditIsRecurring(false)
                actions.setEditRecurrenceInterval(null)
                actions.setEditCronExpression(null)
                actions.setEditEndDate(null)
            } else if (value === 'cron') {
                actions.setEditIsRecurring(true)
                actions.setEditRecurrenceInterval(null)
                actions.setEditCronExpression(values.editCronExpression ?? '')
            } else {
                actions.setEditIsRecurring(true)
                actions.setEditRecurrenceInterval(value)
                actions.setEditCronExpression(null)
            }
        },
        setEditCronExpression: ({ cron }) => {
            if (!cron) {
                return
            }
            const fields = cron.trim().split(/\s+/)
            if (fields.length !== 5) {
                return
            }
            try {
                const timezone = values.projectTimezone
                // Use the later of now or the existing date so that paused/old
                // schedules don't snap to an already-elapsed time. The existing
                // date is a browser-local Dayjs whose wall clock mirrors the
                // project timezone — reinterpret it in project tz to get the real instant.
                const now = new Date()
                const existing = values.editScheduledAt?.tz(timezone, true).toDate()
                const currentDate = existing && existing > now ? existing : now
                const interval = CronExpressionParser.parse(cron, { currentDate, tz: timezone })
                const nextDate = interval.next().toDate()
                actions.setEditScheduledAt(scheduleDateFromStoredISO(nextDate.toISOString(), timezone))
            } catch {
                // Invalid — don't update
            }
        },
        saveEdit: async () => {
            const { editingSchedule, editValidationErrors } = values
            if (!editingSchedule || Object.keys(editValidationErrors).length > 0) {
                if (Object.keys(editValidationErrors).length > 0) {
                    const firstError = Object.values(editValidationErrors)[0] as string
                    lemonToast.error(firstError)
                }
                actions.saveEditFailure()
                return
            }

            const patch: Record<string, unknown> = {}
            const timezone = values.projectTimezone

            // Compare and build patch with only changed fields. The calendar emits browser-local
            // Dayjs values whose wall clock matches the project timezone; convert them back to a
            // project-timezone UTC ISO string before sending.
            const newScheduledAt = values.editScheduledAt
                ? scheduleDateToProjectTzISO(values.editScheduledAt, timezone)
                : null
            const origScheduledAt = editingSchedule.scheduled_at
                ? dayjs(editingSchedule.scheduled_at).toISOString()
                : null
            if (newScheduledAt !== origScheduledAt) {
                patch.scheduled_at = newScheduledAt
            }

            if (editingSchedule.cron_expression !== values.editCronExpression) {
                patch.cron_expression = values.editCronExpression
            }

            if (editingSchedule.recurrence_interval !== values.editRecurrenceInterval) {
                patch.recurrence_interval = values.editRecurrenceInterval
            }

            const newEndDate = values.editEndDate
                ? values.editEndDate.tz(timezone, true).endOf('day').toISOString()
                : null
            const origEndDate = editingSchedule.end_date ? dayjs(editingSchedule.end_date).toISOString() : null
            if (newEndDate !== origEndDate) {
                patch.end_date = newEndDate
            }

            // Use the same derived comparison as hasEditChanges so that
            // editing a paused schedule doesn't silently unpause it.
            const origIsRecurring =
                editingSchedule.is_recurring ||
                !!editingSchedule.recurrence_interval ||
                !!editingSchedule.cron_expression
            if (origIsRecurring !== values.editIsRecurring) {
                patch.is_recurring = values.editIsRecurring
            }

            if (
                editingSchedule.payload.operation === ScheduledChangeOperationType.UpdateStatus &&
                editingSchedule.payload.value !== values.editPayloadValue
            ) {
                patch.payload = {
                    operation: ScheduledChangeOperationType.UpdateStatus,
                    value: values.editPayloadValue,
                }
            }

            if (Object.keys(patch).length === 0) {
                lemonToast.info('No changes to save')
                actions.closeEdit()
                return
            }

            try {
                await api.featureFlags.updateScheduledChange(editingSchedule.team_id, editingSchedule.id, patch)
                lemonToast.success('Schedule updated')
                actions.saveEditSuccess()
                // Reload the schedule list in the parent logic
                featureFlagLogic.findMounted({ id: logicProps.id })?.actions.loadScheduledChanges()
            } catch {
                lemonToast.error('Failed to update schedule')
                actions.saveEditFailure()
            }
        },
    })),
])
