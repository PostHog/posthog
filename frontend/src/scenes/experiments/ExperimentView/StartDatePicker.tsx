import { LemonButton } from '@posthog/lemon-ui'
import { DatePicker } from 'lib/components/DatePicker'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

interface StartDatePickerProps {
    currentStartDate: string
    updateStartDate: (_: string) => void
}

export function StartDatePicker({ currentStartDate, updateStartDate }: StartDatePickerProps): JSX.Element {
    const [isSelectorOpen, setIsSelectorOpen] = useState(false)

    return (
        <div>
            {isSelectorOpen ? (
                <DatePicker
                    onSelect={(date: dayjs.Dayjs) => {
                        updateStartDate(date.toISOString())
                    }}
                    showTime={false}
                    open={true}
                    showToday={false}
                    mode="date"
                    value={dayjs(currentStartDate)}
                    disabledDate={(dateMarker) => {
                        const now = new Date()
                        return dateMarker.toDate().getTime() > now.getTime()
                    }}
                    getPopupContainer={() => {
                        const containerId = 'start-date-picker-container'
                        let container = document.getElementById(containerId)
                        if (container) {
                            return container
                        }
                        container = document.createElement('div')
                        container.id = 'start-date-picker-container'
                        document.body.appendChild(container)
                        return container
                    }}
                    allowClear={false}
                />
            ) : (
                <LemonButton onClick={() => setIsSelectorOpen(true)}>Move experiment start date</LemonButton>
            )}
        </div>
    )
}
