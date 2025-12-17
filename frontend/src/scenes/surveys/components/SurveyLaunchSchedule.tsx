import { Popover, LemonCalendarSelect, LemonButton } from "@posthog/lemon-ui"
import dayjs from "dayjs"
import { useValues, useActions } from "kea"
import { LemonField } from "lib/lemon-ui/LemonField"
import { LemonRadioOption, LemonRadio } from "lib/lemon-ui/LemonRadio"
import { formatDateTime, DATE_TIME_FORMAT_WITHOUT_SECONDS } from "lib/utils"
import { useState, useEffect } from "react"
import { surveyLogic, SurveyScheduleType } from "../surveyLogic"



export default function SurveyLaunchSchedule(): JSX.Element {
    const { survey, startType, endType } = useValues(surveyLogic)
    const { setSurveyValue, setStartType, setEndType } = useActions(surveyLogic)
    const [startDateVisible, setStartDateVisible] = useState(false)
    const [endDateVisible, setEndDateVisible] = useState(false)
    const surveyStartDateTimeOptions: LemonRadioOption<SurveyScheduleType>[] = [
        {
            value: 'manual',
            label: 'When I click Launch',
        },
        {
            value: 'datetime',
            label: 'At a chosen date and time',
        },
    ]
    const surveyEndDateTimeOptions: LemonRadioOption<SurveyScheduleType>[] = [
        {
            value: 'manual',
            label: 'When I click Stop',
        },
        {
            value: 'datetime',
            label: 'At a chosen date and time',
        },
    ]

    const dateRangeError =
        !!survey.scheduled_start_datetime &&
        !!survey.scheduled_end_datetime &&
        dayjs(survey.scheduled_start_datetime).isSameOrAfter(dayjs(survey.scheduled_end_datetime))
    const showDateRangeError = dateRangeError && survey.scheduled_start_datetime && survey.scheduled_end_datetime

    // if we're editing an existing survey we need to initialize the form with the saved values
    // open question: is there a better way to do this using redux?
    useEffect(() => {
        if (survey.scheduled_start_datetime) {
            setStartType('datetime')
        }
        if (survey.scheduled_end_datetime) {
            setEndType('datetime')
        }
    }, [])

    return (
        <>
            <div>
                <h3>
                    When would you like to <b>launch</b> this survey?
                </h3>
                <LemonField.Pure error={showDateRangeError && 'Make sure end date is after start date'}>
                    <LemonRadio
                        value={startType}
                        options={surveyStartDateTimeOptions}
                        onChange={(newValue: SurveyScheduleType) => {
                            if (newValue === 'manual') {
                                setSurveyValue('scheduled_start_datetime', null)
                            }
                            if (newValue === 'datetime' && !survey.scheduled_start_datetime) {
                                setSurveyValue('scheduled_start_datetime', dayjs().toISOString())
                            }
                            setStartType(newValue)
                        }}
                    />
                </LemonField.Pure>
            </div>
            {startType === 'datetime' && (
                <div className="ml-5 mt-2">
                    <Popover
                        actionable
                        overlay={
                            <LemonCalendarSelect
                                value={dayjs(survey.scheduled_start_datetime)}
                                selectionPeriod="upcoming"
                                onChange={(value) => {
                                    setSurveyValue('scheduled_start_datetime', value.toISOString())
                                    setStartDateVisible(false)
                                }}
                                granularity="minute"
                                onClose={() => setStartDateVisible(false)}
                            />
                        }
                        visible={startDateVisible}
                        onClickOutside={() => setStartDateVisible(false)}
                    >
                        <LemonButton type="secondary" onClick={() => setStartDateVisible(!startDateVisible)}>
                            {formatDateTime(dayjs(survey.scheduled_start_datetime), DATE_TIME_FORMAT_WITHOUT_SECONDS)}
                        </LemonButton>
                    </Popover>
                </div>
            )}
            <div className="mt-4">
                <h3>
                    When would you like to <b>stop</b> this survey?
                </h3>
                <LemonField.Pure error={showDateRangeError && 'Make sure end date is after start date'}>
                    <LemonRadio
                        value={endType}
                        options={surveyEndDateTimeOptions}
                        onChange={(newValue: SurveyScheduleType) => {
                            if (newValue === 'manual') {
                                setSurveyValue('scheduled_end_datetime', null)
                            }
                            if (newValue === 'datetime' && !survey.scheduled_end_datetime) {
                                setSurveyValue('scheduled_end_datetime', dayjs().toISOString())
                            }
                            setEndType(newValue)
                        }}
                    />
                </LemonField.Pure>
            </div>
            {endType === 'datetime' && (
                <div className="ml-5 mt-2">
                    <Popover
                        actionable
                        overlay={
                            <LemonCalendarSelect
                                value={dayjs(survey.scheduled_end_datetime)}
                                selectionPeriod="upcoming"
                                onChange={(value) => {
                                    setSurveyValue('scheduled_end_datetime', value.toISOString())
                                    setEndDateVisible(false)
                                }}
                                granularity="minute"
                                onClose={() => setEndDateVisible(false)}
                            />
                        }
                        visible={endDateVisible}
                        onClickOutside={() => setEndDateVisible(false)}
                    >
                        <LemonButton type="secondary" onClick={() => setEndDateVisible(!endDateVisible)}>
                            {formatDateTime(dayjs(survey.scheduled_end_datetime), DATE_TIME_FORMAT_WITHOUT_SECONDS)}
                        </LemonButton>
                    </Popover>
                </div>
            )}
        </>
    )
}