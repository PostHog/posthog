import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCalendarSelectInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import { experimentLogic } from '../experimentLogic'

const ExperimentDate = ({ label, date }: { label: string; date?: string | null }): JSX.Element | null => {
    const [isDatePickerOpen, setIsDatePickerOpen] = useState(false)

    const { changeExperimentStartDate } = useActions(experimentLogic)
    if (!date) {
        return null
    }

    return (
        <div className="block" data-attr="experiment-start-date">
            <div className={clsx('text-xs font-semibold uppercase tracking-wide', isDatePickerOpen && 'text-center')}>
                {label}
            </div>
            <div className="flex">
                {isDatePickerOpen ? (
                    <LemonCalendarSelectInput
                        granularity="minute"
                        visible
                        value={dayjs(date)}
                        onChange={(newDate) => {
                            if (newDate) {
                                changeExperimentStartDate(newDate.toISOString())
                            }
                        }}
                        onClose={() => setIsDatePickerOpen(false)}
                        onClickOutside={() => setIsDatePickerOpen(false)}
                        clearable={false}
                        selectionPeriod="past"
                        buttonProps={{ size: 'xsmall', 'data-attr': 'experiment-start-date-picker' }}
                    />
                ) : (
                    <>
                        <TZLabel time={date} />
                        <LemonButton
                            title="Move start date"
                            data-attr="move-experiment-start-date"
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => setIsDatePickerOpen(true)}
                            noPadding
                            className="ml-2"
                        />
                    </>
                )}
            </div>
        </div>
    )
}

export default ExperimentDate
