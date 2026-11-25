import { capitalizeFirstLetter } from 'lib/utils/strings'

import { ReminderApi } from 'products/reminders/frontend/generated/api.schemas'

export const RECURRENCE_OPTIONS = [
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' },
    { value: 'yearly', label: 'Yearly' },
]

export function scheduleSummary(reminder: ReminderApi): string {
    if (reminder.cron_expression) {
        return `Cron: ${reminder.cron_expression}`
    }
    if (reminder.recurrence_interval) {
        return capitalizeFirstLetter(reminder.recurrence_interval)
    }
    return 'One-off'
}
