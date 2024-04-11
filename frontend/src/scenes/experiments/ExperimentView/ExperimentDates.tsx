import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useAsyncActions, useValues } from 'kea'
import { DatePicker } from 'lib/components/DatePicker'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import { experimentLogic } from '../experimentLogic'

export function ExperimentDates(): JSX.Element {
    const [isSelectorOpen, setIsSelectorOpen] = useState(false)
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, loadExperiment } = useAsyncActions(experimentLogic)
    const { created_at, start_date, end_date } = experiment

    if (!start_date) {
        return (
            <div className="block">
                <div className="text-xs font-semibold uppercase tracking-wide">Creation date</div>
                {created_at && <TZLabel time={created_at} />}
            </div>
        )
    }
    return (
        <>
            <div className="block">
                <div className="text-xs font-semibold uppercase tracking-wide">Start date</div>
                <div className="flex items-center">
                    {isSelectorOpen ? (
                        <DatePicker
                            showTime={true}
                            open={true}
                            value={dayjs(start_date)}
                            onBlur={() => setIsSelectorOpen(false)}
                            onOk={(newStartDate: dayjs.Dayjs) => {
                                updateExperiment({ start_date: newStartDate.toISOString() })
                                    .then(() => loadExperiment())
                                    .catch((error) => console.error('error on loading experiment:', error))
                            }}
                            autoFocus={true}
                            disabledDate={(dateMarker) => {
                                const now = new Date()
                                return dateMarker.toDate().getTime() > now.getTime()
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
                                onClick={() => {
                                    setIsSelectorOpen(true)
                                }}
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
                    <div className="flex items-center">
                        <TZLabel time={end_date} />
                    </div>
                </div>
            )}
        </>
    )
    // return (
    //     <div>
    //         {isSelectorOpen ? (
    //             <DatePicker
    //                 onSelect={(date: dayjs.Dayjs) => {
    //                     updateStartDate(date.toISOString())
    //                 }}
    //                 showTime={false}
    //                 open={true}
    //                 showToday={false}
    //                 mode="date"
    //                 value={dayjs(currentStartDate)}
    //                 disabledDate={(dateMarker) => {
    //                     const now = new Date()
    //                     return dateMarker.toDate().getTime() > now.getTime()
    //                 }}
    //                 getPopupContainer={() => {
    //                     const containerId = 'start-date-picker-container'
    //                     let container = document.getElementById(containerId)
    //                     if (container) {
    //                         return container
    //                     }
    //                     container = document.createElement('div')
    //                     container.id = 'start-date-picker-container'
    //                     document.body.appendChild(container)
    //                     return container
    //                 }}
    //                 allowClear={false}
    //             />
    //         ) : (
    //             <LemonButton onClick={() => setIsSelectorOpen(true)}>Move experiment start date</LemonButton>
    //         )}
    //     </div>
    // )
}
