import './EditSurvey.scss'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSnack, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { Survey, SurveySchedule, SurveyType } from '~/types'

import { SurveyEditSection, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'

function doesSurveyHaveOtherDisplayConditions(survey: Pick<Survey, 'conditions'>): boolean {
    return !!(
        (survey.conditions?.events?.values?.length ?? 0) > 0 ||
        survey.conditions?.url ||
        survey.conditions?.selector ||
        (survey?.conditions?.deviceTypes?.length ?? 0) > 0 ||
        (survey?.conditions?.seenSurveyWaitPeriodInDays ?? 0) > 0
    )
}

function SurveyIterationOptions(): JSX.Element {
    const { showSurveyRepeatSchedule, survey } = useValues(surveyLogic)
    const { setSurveyValue, setSelectedSection } = useActions(surveyLogic)
    const { surveysRecurringScheduleAvailable } = useValues(surveysLogic)

    const surveysRecurringScheduleDisabledReason = surveysRecurringScheduleAvailable
        ? undefined
        : 'Upgrade your plan to use repeating surveys'

    return (
        <>
            <LemonField.Pure
                info="Showing a survey all the time requires at least version 1.220.0 of posthog-js"
                label={<h3 className="mb-0">How often should we show this survey?</h3>}
            >
                <LemonRadio
                    value={survey.schedule ?? SurveySchedule.Once}
                    onChange={(newValue) => {
                        setSurveyValue('schedule', newValue)
                        if (newValue === SurveySchedule.Once || newValue === SurveySchedule.Always) {
                            setSurveyValue('iteration_count', 0)
                            setSurveyValue('iteration_frequency_days', 0)
                        } else if (newValue === SurveySchedule.Recurring) {
                            setSurveyValue('iteration_count', 1)
                            setSurveyValue('iteration_frequency_days', 90)
                        }
                    }}
                    options={[
                        {
                            value: SurveySchedule.Once,
                            label: 'Once',
                            'data-attr': 'survey-iteration-frequency-days',
                        },
                        {
                            value: SurveySchedule.Recurring,
                            label: 'Repeat on a schedule',
                            'data-attr': 'survey-iteration-frequency-days',
                            disabledReason: surveysRecurringScheduleDisabledReason,
                        },
                        {
                            value: SurveySchedule.Always,
                            label: 'Every time the display conditions are met',
                            'data-attr': 'survey-iteration-frequency-days',
                        },
                    ]}
                />
                {survey.type === SurveyType.Popover && survey.schedule === SurveySchedule.Always && (
                    <LemonBanner type="warning">
                        {doesSurveyHaveOtherDisplayConditions(survey) ? (
                            <>
                                <p>
                                    This survey will be shown every time the display conditions are met – which
                                    potentially makes it possible to show the same survey multiple times. Double check
                                    your display conditions below.
                                </p>
                                <p className="font-normal">
                                    If this is not what you want, change to a scheduled or one-time survey, or{' '}
                                    <Link onClick={() => setSelectedSection(SurveyEditSection.DisplayConditions)}>
                                        add other display conditions here
                                    </Link>
                                    .
                                </p>
                            </>
                        ) : (
                            <>
                                <p>
                                    If you select "Every time the display conditions are met" for a Popover survey, it
                                    will behave like a permanent popup in your application. Make sure this is what you
                                    want.
                                </p>
                            </>
                        )}
                    </LemonBanner>
                )}
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

    const canSurveyBeRepeated = Boolean(
        survey.conditions?.events?.repeatedActivation && survey.conditions?.events?.values?.length > 0
    )

    return (
        <div className="mt-4">
            {canSurveyBeRepeated ? (
                <span className="font-medium">
                    <h3 className="mb-0">How often should we show this survey?</h3>
                    <IconInfo className="mr-0.5" /> This survey is displayed whenever the{' '}
                    <LemonSnack>{survey.conditions?.events?.values.map((v) => v.name).join(', ')}</LemonSnack>{' '}
                    <span>{survey.conditions?.events?.values.length === 1 ? 'event is' : 'events are'}</span> triggered.
                    So these settings are not applicable. If you want, remove the event targeting in the{' '}
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
