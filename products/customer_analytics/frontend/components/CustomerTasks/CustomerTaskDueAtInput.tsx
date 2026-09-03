import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs, dayjsLocalToTimezone, dayjsUtcToTimezone } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerTaskEditDisabledReason } from './customerTaskFilters'
import type { customerTasksLogicType } from './customerTasksLogic'
export interface CustomerTaskDueAtInputProps {
    task: CustomerTaskApi
    logic: import('kea').BuiltLogic<customerTasksLogicType>
    timezone: string
}
export function CustomerTaskDueAtInput({ task, logic, timezone }: CustomerTaskDueAtInputProps): JSX.Element {
    const { mutationKeys } = useValues(logic)
    const { updateTask } = useActions(logic)
    const saving = Boolean(mutationKeys[task.id])
    const overdue = Boolean(
        task.due_at && task.status !== 'completed' && task.status !== 'canceled' && dayjs(task.due_at).isBefore(dayjs())
    )
    return (
        <LemonCalendarSelectInput
            value={task.due_at ? dayjsUtcToTimezone(task.due_at, timezone) : null}
            onChange={(value) =>
                updateTask(task.id, {
                    due_at: value
                        ? dayjsLocalToTimezone(value.format('YYYY-MM-DDTHH:mm'), timezone).toISOString()
                        : null,
                })
            }
            granularity="minute"
            format="MMM D, YYYY HH:mm"
            use24HourFormat
            clearable
            placeholder="No due date"
            buttonProps={{
                type: 'tertiary',
                size: 'small',
                loading: saving,
                disabledReason: customerTaskEditDisabledReason(task) ?? (saving ? 'Saving' : undefined),
                className: overdue ? 'text-danger' : undefined,
                'data-attr': 'customer-task-due',
                children: task.due_at ? (
                    <TZLabel time={task.due_at} noStyles className={overdue ? 'text-danger' : undefined} />
                ) : (
                    'No due date'
                ),
            }}
        />
    )
}
