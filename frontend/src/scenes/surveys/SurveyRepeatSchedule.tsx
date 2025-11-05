import './EditSurvey.scss'

import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSnack, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { pluralize } from 'lib/utils'
import { LinkToSurveyFormSection } from 'scenes/surveys/components/LinkToSurveyFormSection'
import { SURVEY_FORM_INPUT_IDS } from 'scenes/surveys/constants'

import { Survey, SurveySchedule, SurveyType } from '~/types'

import { SurveyEditSection, surveyLogic } from './surveyLogic'

function doesSurveyHaveDisplayConditions(survey: Pick<Survey, 'conditions'>): boolean {
    return !!(
        (survey.conditions?.events?.values?.length ?? 0) > 0 ||
        survey.conditions?.url ||
        survey.conditions?.selector ||
        (survey?.conditions?.deviceTypes?.length ?? 0) > 0 ||
        (survey?.conditions?.seenSurveyWaitPeriodInDays ?? 0) > 0
    )
}

function AlwaysScheduleBanner({
    survey,
}: {
    survey: Pick<Survey, 'type' | 'schedule' | 'conditions'>
}): JSX.Element | null {
    const { setSelectedSection, setSurveyValue } = useActions(surveyLogic)
    const { hasTargetingSet } = useValues(surveyLogic)
    const doesSurveyHaveWaitPeriod = (survey?.conditions?.seenSurveyWaitPeriodInDays ?? 0) > 0

    const handleWaitPeriodClick = (): void => {
        setSelectedSection(SurveyEditSection.DisplayConditions)
        // if the survey has no targeting set, set the url to an empty string so the full section is rendered
        if (!hasTargetingSet) {
            setSurveyValue('conditions', {
                ...survey.conditions,
                url: '',
            })
        }
        // timeout necessary so the section is rendered
        setTimeout(() => {
            document.getElementById(SURVEY_FORM_INPUT_IDS.WAIT_PERIOD_INPUT)?.focus()
        }, 200)
    }

    if (doesSurveyHaveWaitPeriod) {
        return (
            <LemonBanner type="info">
                This survey will be shown every {pluralize(survey.conditions?.seenSurveyWaitPeriodInDays ?? 0, 'day')},
                as long as other display conditions are met.
            </LemonBanner>
        )
    }

    if (doesSurveyHaveDisplayConditions(survey)) {
        return (
            <LemonBanner type="warning">
                <p>
                    This popover will reappear every time its display conditions are met. This might lead to users
                    seeing the survey very frequently.
                </p>
                <p className="font-normal">
                    If this isn't intended, consider&nbsp;
                    <Link onClick={handleWaitPeriodClick}>adding a wait period</Link>.
                </p>
            </LemonBanner>
        )
    }

    return (
        <LemonBanner type="warning">
            <p>
                Setting a popover survey to show 'Always' without any display conditions will make it appear
                persistently. Ensure this is the desired behavior.
            </p>
            <p className="font-normal">
                If not, consider&nbsp;
                <Link onClick={handleWaitPeriodClick}>adding a wait period</Link>
                &nbsp;or changing its frequency.
            </p>
        </LemonBanner>
    )
}

function SurveyIterationOptions(): JSX.Element {
    const { showSurveyRepeatSchedule, survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    return (
        <>
            <LemonField.Pure
                info="Showing a survey every time the display conditions are met requires at least version 1.234.11 of posthog-js"
                label={<h3 className="mb-0">How often should we show this survey to a person?</h3>}
            >
                <LemonRadio
                    value={survey.schedule ?? SurveySchedule.Once}
                    onChange={(newValue) => {
                        setSurveyValue('schedule', newValue)
                        if (newValue === SurveySchedule.Once || newValue === SurveySchedule.Always) {
                            setSurveyValue('iteration_count', 0)
                            setSurveyValue('iteration_frequency_days', 0)
                        } else if (newValue === SurveySchedule.Recurring) {
                            setSurveyValue('iteration_count', 2)
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
                            description: showSurveyRepeatSchedule ? (
                                <div className="flex flex-row gap-2 items-center text-secondary">
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
                                                    value={value || 2}
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
                            ) : undefined,
                        },
                        {
                            value: SurveySchedule.Always,
                            label: 'Every time the display conditions are met',
                            'data-attr': 'survey-iteration-frequency-days',
                        },
                    ]}
                />
                {survey.schedule === SurveySchedule.Always && survey.type === SurveyType.Popover && (
                    <AlwaysScheduleBanner survey={survey} />
                )}
            </LemonField.Pure>
        </>
    )
}

export function SurveyRepeatSchedule(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    const canSurveyBeRepeated = Boolean(
        survey.conditions?.events?.repeatedActivation && survey.conditions?.events?.values?.length > 0
    )

    return (
        <div className="mt-4">
            {canSurveyBeRepeated ? (
                <span className="font-medium">
                    <h3 className="mb-0">How often should we show this survey to a person?</h3>
                    <IconInfo className="mr-0.5" /> This survey is displayed whenever the&nbsp;
                    <LemonSnack>{survey.conditions?.events?.values.map((v) => v.name).join(', ')}</LemonSnack>&nbsp;
                    <span>{survey.conditions?.events?.values.length === 1 ? 'event is' : 'events are'}</span> triggered.
                    So these settings are not applicable. If you want, remove the event targeting in the&nbsp;
                    <LinkToSurveyFormSection section={SurveyEditSection.DisplayConditions} />.
                </span>
            ) : (
                <SurveyIterationOptions />
            )}
        </div>
    )
}
