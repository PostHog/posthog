import { IconCalendar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils/datetime'

const DATETIME_FORMAT = 'MMM D - HH:mm'

interface SnoozeButtonProps {
    onChange: (snoonzeUntil: string) => void
    value?: string
    disabledReason?: string
}

export function SnoozeButton({ onChange, value, disabledReason }: SnoozeButtonProps): JSX.Element {
    if (disabledReason) {
        return (
            <LemonButton type="secondary" size="medium" icon={<IconCalendar />} disabledReason={disabledReason}>
                Snooze until
            </LemonButton>
        )
    }

    return (
        <DateFilter
            dateFrom={value ?? null}
            onChange={(snoozeUntil) => {
                if (snoozeUntil) {
                    onChange(snoozeUntil)
                }
            }}
            placeholder="Snooze until"
            max={31}
            isFixedDateMode
            showRollingRangePicker={false}
            allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
            showCustom
            dateOptions={[
                {
                    key: 'Tomorrow',
                    values: ['+1d'],
                    getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.add(1, 'd'), DATETIME_FORMAT),
                    defaultInterval: 'day',
                },
                {
                    key: 'One week from now',
                    values: ['+1w'],
                    getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.add(1, 'w'), DATETIME_FORMAT),
                    defaultInterval: 'day',
                },
            ]}
            size="medium"
        />
    )
}
