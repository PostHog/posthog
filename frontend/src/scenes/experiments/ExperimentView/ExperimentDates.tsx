import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCalendarSelectInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import { experimentLogic } from '../experimentLogic'

export function ExperimentDates(): JSX.Element {
    const [isStartDatePickerOpen, setIsStartDatePickerOpen] = useState(false)
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate } = useActions(experimentLogic)
    const { created_at, start_date, end_date } = experiment

    if (!start_date) {
        if (!created_at) {
            return <></>
        }
        return (
            <div className="block" data-attr="experiment-creation-date">
                <div className="text-xs font-semibold uppercase tracking-wide">Creation date</div>
                <TZLabel time={created_at} />
            </div>
        )
    }
    return (
        <>
            <div className="block" data-attr="experiment-start-date">
                <div
                    className={clsx(
                        'text-xs font-semibold uppercase tracking-wide',
                        isStartDatePickerOpen && 'text-center'
                    )}
                >
                    Start date
                </div>
                <div className="flex">
                    {isStartDatePickerOpen ? (
                        <LemonCalendarSelectInput
                            granularity="minute"
                            visible
                            value={dayjs(start_date)}
                            onChange={(newStartDate) => {
                                if (newStartDate) {
                                    changeExperimentStartDate(newStartDate.toISOString())
                                }
                            }}
                            onClose={() => setIsStartDatePickerOpen(false)}
                            onClickOutside={() => setIsStartDatePickerOpen(false)}
                            clearable={false}
                            selectionPeriod="past"
                            buttonProps={{ size: 'xsmall', 'data-attr': 'experiment-start-date-picker' }}
                        />
                    ) : (
                        <>
                            <TZLabel time={start_date} />
                            <LemonButton
                                title="Move start date"
                                data-attr="move-experiment-start-date"
                                icon={<IconPencil />}
                                size="small"
                                onClick={() => setIsStartDatePickerOpen(true)}
                                noPadding
                                className="ml-2"
                            />
                        </>
                    )}
                </div>
            </div>
            {end_date && (
                <div className="block" data-attr="experiment-end-date">
                    <div className="text-xs font-semibold uppercase tracking-wide">End date</div>
                    {/* Flex class here is for the end date to have same appearance as the start date. */}
                    <div className="flex">
                        <TZLabel time={end_date} />
                    </div>
                </div>
            )}
        </>
    )
}
