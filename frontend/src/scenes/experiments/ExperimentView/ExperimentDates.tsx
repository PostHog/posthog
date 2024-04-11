import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useAsyncActions, useValues } from 'kea'
import { DatePicker } from 'lib/components/DatePicker'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import { experimentLogic } from '../experimentLogic'

export function ExperimentDates(): JSX.Element {
    const [isStartDatePickerOpen, setIsStartDatePickerOpen] = useState(false)
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, loadExperiment } = useAsyncActions(experimentLogic)
    const { created_at, start_date, end_date } = experiment

    if (!start_date) {
        if (!created_at) {
            return <></>
        }
        return (
            <div className="block">
                <div className="text-xs font-semibold uppercase tracking-wide">Creation date</div>
                <TZLabel time={created_at} />
            </div>
        )
    }
    return (
        <>
            <div className="block">
                <div className="text-xs font-semibold uppercase tracking-wide">Start date</div>
                <div className="flex">
                    {isStartDatePickerOpen ? (
                        <DatePicker
                            showTime={true}
                            showSecond={false}
                            open={true}
                            value={dayjs(start_date)}
                            onBlur={() => setIsStartDatePickerOpen(false)}
                            onOk={(newStartDate: dayjs.Dayjs) => {
                                updateExperiment({ start_date: newStartDate.toISOString() })
                                    .then(() => loadExperiment())
                                    .catch((error) => console.error('error on loading an experiment:', error))
                            }}
                            autoFocus={true}
                            disabledDate={(dateMarker) => {
                                return dateMarker.toDate() > new Date()
                            }}
                            allowClear={false}
                        />
                    ) : (
                        <>
                            <TZLabel time={start_date} />
                            <LemonButton
                                title="Move start date"
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
                <div className="block">
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
