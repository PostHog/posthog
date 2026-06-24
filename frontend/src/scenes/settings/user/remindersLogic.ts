import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { timeZoneLabel } from 'lib/utils/timezones'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import {
    remindersCreate,
    remindersDestroy,
    remindersList,
    remindersPartialUpdate,
} from 'products/reminders/frontend/generated/api'
import { RecurrenceIntervalEnumApi, ReminderApi } from 'products/reminders/frontend/generated/api.schemas'

import type { remindersLogicType } from './remindersLogicType'

export type ReminderScheduleType = 'one-off' | 'repeats' | 'advanced'

export interface ReminderFormValues {
    title: string
    message: string
    team: number | null
    scheduleType: ReminderScheduleType
    scheduled_at: string | null
    recurrence_interval: RecurrenceIntervalEnumApi | null
    cron_expression: string
    timezone: string
    end_date: string | null
}

// Sentinel id used while creating a brand-new reminder (mirrors the personalAPIKeysLogic pattern).
const NEW = 'new'

// Personal reminders default to the user's own timezone, not the project's.
function getLocalTimezone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
        return 'UTC'
    }
}

function scheduleTypeForReminder(reminder: ReminderApi): ReminderScheduleType {
    if (reminder.cron_expression) {
        return 'advanced'
    }
    if (reminder.recurrence_interval) {
        return 'repeats'
    }
    return 'one-off'
}

export const remindersLogic = kea<remindersLogicType>([
    path(['scenes', 'settings', 'user', 'remindersLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], preflightLogic, ['preflight']],
    })),
    actions({
        setEditingReminderId: (id: string | null) => ({ id }),
    }),
    reducers({
        editingReminderId: [
            null as string | null,
            {
                setEditingReminderId: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values }) => ({
        reminders: [
            [] as ReminderApi[],
            {
                loadReminders: async () => {
                    const response = await remindersList()
                    return response.results
                },
                deleteReminder: async (id: string) => {
                    await remindersDestroy(id)
                    return values.reminders.filter((reminder) => reminder.id !== id)
                },
            },
        ],
    })),
    forms(({ values, actions }) => ({
        reminderForm: {
            defaults: {
                title: '',
                message: '',
                team: null,
                scheduleType: 'one-off',
                scheduled_at: null,
                recurrence_interval: null,
                cron_expression: '',
                timezone: getLocalTimezone(),
                end_date: null,
            } as ReminderFormValues,
            errors: ({
                title,
                scheduleType,
                scheduled_at,
                recurrence_interval,
                cron_expression,
            }: ReminderFormValues) => ({
                title: !title?.trim() ? 'A title is required' : undefined,
                scheduled_at:
                    scheduleType !== 'one-off'
                        ? undefined
                        : !scheduled_at
                          ? 'Pick when this reminder should fire'
                          : values.isScheduleEditable && dayjs(scheduled_at).isBefore(dayjs())
                            ? 'The time must be in the future'
                            : undefined,
                recurrence_interval:
                    scheduleType === 'repeats' && !recurrence_interval ? 'Choose how often it repeats' : undefined,
                cron_expression:
                    scheduleType === 'advanced' && !cron_expression?.trim() ? 'Enter a cron expression' : undefined,
            }),
            submit: async (formValues) => {
                const organization = values.currentOrganization?.id
                if (!organization) {
                    return
                }
                const payload = {
                    organization,
                    team: formValues.team,
                    title: formValues.title.trim(),
                    message: formValues.message?.trim() || '',
                    timezone: formValues.timezone,
                    scheduled_at: formValues.scheduleType === 'one-off' ? formValues.scheduled_at : null,
                    recurrence_interval: formValues.scheduleType === 'repeats' ? formValues.recurrence_interval : null,
                    cron_expression: formValues.scheduleType === 'advanced' ? formValues.cron_expression : null,
                    end_date: formValues.scheduleType === 'one-off' ? null : formValues.end_date,
                }
                const editingId = values.editingReminderId
                try {
                    if (editingId && editingId !== NEW) {
                        await remindersPartialUpdate(editingId, payload)
                        lemonToast.success('Reminder updated')
                    } else {
                        await remindersCreate(payload)
                        lemonToast.success('Reminder created')
                    }
                } catch (error: any) {
                    lemonToast.error(error?.data?.detail || error?.detail || 'Could not save the reminder')
                    return
                }
                actions.setEditingReminderId(null)
                actions.loadReminders()
            },
        },
    })),
    selectors({
        editingReminder: [
            (s) => [s.editingReminderId, s.reminders],
            (editingReminderId, reminders): ReminderApi | null =>
                editingReminderId && editingReminderId !== NEW
                    ? (reminders.find((reminder) => reminder.id === editingReminderId) ?? null)
                    : null,
        ],
        isScheduleEditable: [
            (s) => [s.editingReminderId, s.editingReminder],
            (editingReminderId, editingReminder): boolean =>
                editingReminderId === NEW || editingReminder?.status === 'active',
        ],
        projectOptions: [
            (s) => [s.currentOrganization],
            (currentOrganization): { value: number | null; label: string }[] => [
                { value: null, label: 'Organization-wide (no project)' },
                ...(currentOrganization?.teams ?? []).map((team) => ({ value: team.id, label: team.name })),
            ],
        ],
        timezoneOptions: [
            (s) => [s.preflight],
            (preflight): { key: string; label: string }[] =>
                Object.entries(preflight?.available_timezones ?? {}).map(([tz, offset]) => ({
                    key: tz,
                    label: timeZoneLabel(tz, offset),
                })),
        ],
    }),
    listeners(({ actions, values }) => ({
        setEditingReminderId: ({ id }) => {
            if (!id) {
                return
            }
            const reminder = id === NEW ? null : values.reminders.find((r) => r.id === id)
            actions.resetReminderForm({
                title: reminder?.title ?? '',
                message: reminder?.message ?? '',
                team: reminder?.team ?? null,
                scheduleType: reminder ? scheduleTypeForReminder(reminder) : 'one-off',
                scheduled_at: reminder?.scheduled_at ?? null,
                recurrence_interval: (reminder?.recurrence_interval as RecurrenceIntervalEnumApi) || null,
                cron_expression: reminder?.cron_expression ?? '',
                timezone: reminder?.timezone || getLocalTimezone(),
                end_date: reminder?.end_date ?? null,
            })
        },
        deleteReminderSuccess: () => {
            lemonToast.success('Reminder deleted')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadReminders()
    }),
])
