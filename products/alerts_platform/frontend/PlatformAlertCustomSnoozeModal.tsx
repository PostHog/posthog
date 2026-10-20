import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import { platformAlertLogic } from './platformAlertLogic'

export function PlatformAlertCustomSnoozeModal(): JSX.Element {
    const { customSnoozeGroupKey, snoozingGroupKey } = useValues(platformAlertLogic)
    const { closeCustomSnooze, snoozeGroupUntil } = useActions(platformAlertLogic)

    return (
        <LemonModal
            isOpen={customSnoozeGroupKey !== null}
            onClose={closeCustomSnooze}
            title="Snooze group until"
            hideCloseButton
            description="Pick a time within the next 30 days. The group keeps being checked, and a firing group stays firing. Only its notifications are held."
        >
            {customSnoozeGroupKey !== null && (
                <LemonCalendarSelect
                    value={dayjs().add(1, 'day').startOf('hour')}
                    granularity="minute"
                    selectionPeriod="upcoming"
                    loading={snoozingGroupKey === customSnoozeGroupKey}
                    onChange={(date) => snoozeGroupUntil(customSnoozeGroupKey, date.toISOString())}
                    onClose={closeCustomSnooze}
                />
            )}
        </LemonModal>
    )
}
