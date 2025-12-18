import { useMemo, useState } from 'react'

import { LemonButton, LemonCalendarSelect, Popover } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { DATE_TIME_FORMAT_WITHOUT_SECONDS, formatDateTime } from 'lib/utils'
import { SurveyScheduleType } from 'scenes/surveys/surveyLogic'

export type SurveySchedulePickerProps = {
    value: string | undefined
    onChange: (value: string | undefined) => void
    manualLabel: string
    datetimeLabel: string
    defaultDatetimeValue?: () => string
}

export function SurveySchedulePicker({
    value,
    onChange,
    manualLabel,
    datetimeLabel,
    defaultDatetimeValue,
}: SurveySchedulePickerProps): JSX.Element {
    const [dateVisible, setDateVisible] = useState(false)

    const scheduleType: SurveyScheduleType = value ? 'datetime' : 'manual'

    const options: LemonRadioOption<SurveyScheduleType>[] = useMemo(
        () => [
            { value: 'manual', label: manualLabel },
            { value: 'datetime', label: datetimeLabel },
        ],
        [datetimeLabel, manualLabel]
    )

    return (
        <>
            <LemonField.Pure>
                <LemonRadio
                    value={scheduleType}
                    options={options}
                    onChange={(newValue: SurveyScheduleType) => {
                        if (newValue === 'manual') {
                            setDateVisible(false)
                            onChange(undefined)
                        } else {
                            onChange(value ?? defaultDatetimeValue?.() ?? dayjs().toISOString())
                        }
                    }}
                />
            </LemonField.Pure>

            {scheduleType === 'datetime' && value && (
                <div className="ml-5 mt-2">
                    <Popover
                        actionable
                        overlay={
                            <LemonCalendarSelect
                                value={dayjs(value)}
                                selectionPeriod="upcoming"
                                onChange={(nextValue) => {
                                    onChange(nextValue.toISOString())
                                    setDateVisible(false)
                                }}
                                granularity="minute"
                                onClose={() => setDateVisible(false)}
                            />
                        }
                        visible={dateVisible}
                        onClickOutside={() => setDateVisible(false)}
                    >
                        <LemonButton type="secondary" onClick={() => setDateVisible(!dateVisible)}>
                            {formatDateTime(dayjs(value), DATE_TIME_FORMAT_WITHOUT_SECONDS)}
                        </LemonButton>
                    </Popover>
                </div>
            )}
        </>
    )
}
