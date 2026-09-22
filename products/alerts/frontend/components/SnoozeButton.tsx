import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils/datetime'

const DATETIME_FORMAT = 'MMM D - HH:mm'

interface SnoozeButtonProps {
    onChange: (snoonzeUntil: string) => void
    onClear?: () => void
    value?: string
    disabledReason?: string
}

export function SnoozeButton({ onChange, onClear, value, disabledReason }: SnoozeButtonProps): JSX.Element {
    if (disabledReason) {
        return (
            <LemonButton type="secondary" size="medium" icon={<IconCalendar />} disabledReason={disabledReason}>
                Snooze until
            </LemonButton>
        )
    }

    const footerComponent =
        onClear && value
            ? (onClose: () => void): JSX.Element => (
                  <>
                      <LemonDivider />
                      <LemonButton
                          onClick={() => {
                              onClear()
                              onClose()
                          }}
                          size="medium"
                          status="danger"
                          fullWidth
                      >
                          Clear snooze
                      </LemonButton>
                  </>
              )
            : undefined

    return (
        <div className="flex items-center gap-2">
            {value ? <span className="text-sm text-muted-alt">Snoozed until</span> : null}
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
                footerComponent={footerComponent}
                dateOptions={[
                    {
                        key: '30 minutes',
                        values: ['+30m'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.add(30, 'm'), DATETIME_FORMAT),
                        defaultInterval: 'minute',
                    },
                    {
                        key: '1 hour',
                        values: ['+1h'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.add(1, 'h'), DATETIME_FORMAT),
                        defaultInterval: 'hour',
                    },
                    {
                        key: '4 hours',
                        values: ['+4h'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.add(4, 'h'), DATETIME_FORMAT),
                        defaultInterval: 'hour',
                    },
                    {
                        key: '24 hours',
                        values: ['+24h'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.add(24, 'h'), DATETIME_FORMAT),
                        defaultInterval: 'day',
                    },
                ]}
                size="medium"
            />
        </div>
    )
}
