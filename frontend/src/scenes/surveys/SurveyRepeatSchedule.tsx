import './EditSurvey.scss'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSnack, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { ScheduleType, SurveyEditSection, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'

function SurveyIterationOptions(): JSX.Element {
    const { showSurveyRepeatSchedule, schedule } = useValues(surveyLogic)
    const { setSurveyValue, setSchedule } = useActions(surveyLogic)
    const { surveysRecurringScheduleAvailable } = useValues(surveysLogic)

    const surveysRecurringScheduleDisabledReason = surveysRecurringScheduleAvailable
        ? undefined
        : 'Upgrade your plan to use repeating surveys'

    return (
        <>
            <LemonField.Pure>
                <LemonRadio
                    value={schedule}
                    onChange={(newValue) => {
                        setSchedule(newValue as ScheduleType)
                        if (newValue === 'once') {
                            setSurveyValue('iteration_count', 0)
                            setSurveyValue('iteration_frequency_days', 0)
                        } else if (newValue === 'recurring') {
                            setSurveyValue('iteration_count', 1)
                            setSurveyValue('iteration_frequency_days', 90)
                        }
                    }}
                    options={[
                        {
                            value: 'once',
                            label: 'Once',
                            'data-attr': 'survey-iteration-frequency-days',
                        },
                        {
                            value: 'recurring',
                            label: 'Repeat on a schedule',
                            'data-attr': 'survey-iteration-frequency-days',
                            disabledReason: surveysRecurringScheduleDisabledReason,
                        },
                    ]}
                />
            </LemonField.Pure>
            {showSurveyRepeatSchedule && (
                <div className="flex flex-row gap-2 items-center mt-2 ml-5">
                    Repeat this survey{' '}
                    <LemonField name="iteration_count">
                        {({ onChange, value }) => {
                            return (
                                <LemonInput
                                    type="number"
                                    data-attr="survey-iteration-count"
                                    size="small"
                                    min={1}
                                    // NB this is enforced in the API too
                                    max={500}
                                    value={value || 1}
                                    onChange={(newValue) => {
                                        if (newValue && newValue > 0) {
                                            onChange(newValue)
                                        } else {
                                            onChange(null)
                                        }
                                    }}
                                    className="w-16"
                                />
                            )
                        }}
                    </LemonField>{' '}
                    times, once every
                    <LemonField name="iteration_frequency_days">
                        {({ onChange, value }) => {
                            return (
                                <LemonInput
                                    type="number"
                                    data-attr="survey-iteration-frequency-days"
                                    size="small"
                                    min={1}
                                    value={value || 90}
                                    onChange={(newValue) => {
                                        if (newValue && newValue > 0) {
                                            onChange(newValue)
                                        } else {
                                            onChange(null)
                                        }
                                    }}
                                    className="w-16"
                                />
                            )
                        }}
                    </LemonField>{' '}
                    days
                </div>
            )}
        </>
    )
}

export function SurveyRepeatSchedule(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSelectedSection } = useActions(surveyLogic)

    const canSurveyBeRepeated = survey.conditions?.events?.repeatedActivation

    return (
        <div className="mt-4">
            <h3> How often should we show this survey? </h3>
            {canSurveyBeRepeated ? (
                <span className="font-medium">
                    <IconInfo className="mr-0.5" /> This survey is displayed whenever the event{' '}
                    <LemonSnack>{survey.conditions?.events?.values.map((v) => v.name).join(', ')}</LemonSnack> is
                    triggered. So these settings are not applicable. If you want, remove the event targeting in the{' '}
                    <Link onClick={() => setSelectedSection(SurveyEditSection.DisplayConditions)}>
                        display conditions section
                    </Link>
                    .
                </span>
            ) : (
                <SurveyIterationOptions />
            )}
        </div>
    )
}
