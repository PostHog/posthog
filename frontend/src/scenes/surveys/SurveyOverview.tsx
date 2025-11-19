import { useActions, useValues } from 'kea'

import { IconComment } from '@posthog/icons'
import { LemonDivider, Link } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart, IconGridView, IconLink, IconListView } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils'
import { CopySurveyLink } from 'scenes/surveys/CopySurveyLink'
import { SurveyDisplaySummary } from 'scenes/surveys/Survey'
import { SurveyAPIEditor } from 'scenes/surveys/SurveyAPIEditor'
import { SurveyFormAppearance } from 'scenes/surveys/SurveyFormAppearance'
import { FirstSurveyHelper } from 'scenes/surveys/components/empty-state/FirstSurveyHelper'
import {
    SURVEY_EMPTY_STATE_EXPERIMENT_VARIANT,
    SURVEY_TYPE_LABEL_MAP,
    SurveyQuestionLabel,
} from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyQuestionType, SurveySchedule as SurveyScheduleEnum, SurveyType } from '~/types'

function SurveySchedule(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    if (survey.schedule === SurveyScheduleEnum.Recurring && survey.iteration_count && survey.iteration_frequency_days) {
        return (
            <span>
                Repeats every {survey.iteration_frequency_days}{' '}
                {pluralize(survey.iteration_frequency_days, 'day', 'days', false)}, {survey.iteration_count}{' '}
                {pluralize(survey.iteration_count, 'time', 'times', false)}
            </span>
        )
    }

    if (survey.schedule === SurveyScheduleEnum.Always) {
        return <span>Always</span>
    }

    // Default case: survey is scheduled to run once
    return <span>Once</span>
}

function SurveyOption({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col">
            <dt className="card-secondary">{label}</dt>
            <dd>{children}</dd>
        </div>
    )
}

const QuestionIconMap = {
    [SurveyQuestionType.Open]: <IconComment className="text-muted" />,
    [SurveyQuestionType.Link]: <IconLink className="text-muted" />,
    [SurveyQuestionType.Rating]: <IconAreaChart className="text-muted" />,
    [SurveyQuestionType.SingleChoice]: <IconListView className="text-muted" />,
    [SurveyQuestionType.MultipleChoice]: <IconGridView className="text-muted" />,
}

export function SurveyOverview({ onTabChange }: { onTabChange?: (tab: string) => void }): JSX.Element {
    const { survey, selectedPageIndex, targetingFlagFilters } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)

    const isExternalSurvey = survey.type === SurveyType.ExternalSurvey

    const { surveyUsesLimit, surveyUsesAdaptiveLimit } = useValues(surveyLogic)

    return (
        <div className="flex flex-col gap-8">
            <FlaggedFeature
                flag={FEATURE_FLAGS.SURVEY_EMPTY_STATE_V2}
                match={SURVEY_EMPTY_STATE_EXPERIMENT_VARIANT.TEST}
            >
                <FirstSurveyHelper onTabChange={onTabChange} />
            </FlaggedFeature>
            <div className="flex flex-col xl:grid xl:grid-cols-[1fr_400px] gap-x-4">
                <dl className="flex flex-col gap-4 flex-1 overflow-hidden">
                    <SurveyOption label="Display mode">
                        <div className="flex flex-col">
                            <div className="flex flex-row items-center gap-2">
                                {SURVEY_TYPE_LABEL_MAP[survey.type]}
                                {isExternalSurvey && <CopySurveyLink surveyId={survey.id} className="w-fit" />}
                            </div>
                            {isExternalSurvey && (
                                <span>
                                    Responses are anonymous by default. To identify respondents, add the{' '}
                                    <code className="bg-surface-tertiary px-1 rounded">?distinct_id=user123</code> to
                                    the URL.{' '}
                                    <Link
                                        to="https://posthog.com/docs/surveys/creating-surveys#identifying-respondents-on-hosted-surveys"
                                        target="_blank"
                                    >
                                        Check more details in the documentation
                                    </Link>
                                    .
                                </span>
                            )}
                        </div>
                    </SurveyOption>
                    <SurveyOption label={pluralize(survey.questions.length, 'Question', 'Questions', false)}>
                        {survey.questions.map((q, idx) => {
                            return (
                                <div key={q.id ?? idx} className="flex flex-col lg:gap-4 lg:flex-row justify-between">
                                    <span className="flex-1 truncate">
                                        {idx + 1}. {q.question}
                                    </span>
                                    <span className="flex items-center gap-1 text-xs text-muted">
                                        {QuestionIconMap[q.type]}
                                        {SurveyQuestionLabel[q.type]}
                                    </span>
                                </div>
                            )
                        })}
                    </SurveyOption>
                    {(survey.start_date || survey.end_date) && (
                        <div className="flex gap-16">
                            {survey.start_date && (
                                <SurveyOption label="Start date">
                                    <TZLabel time={survey.start_date} />
                                </SurveyOption>
                            )}
                            {survey.end_date && (
                                <SurveyOption label="End date">
                                    <TZLabel time={survey.end_date} />
                                </SurveyOption>
                            )}
                        </div>
                    )}
                    <SurveyOption label="Schedule">
                        <SurveySchedule />
                    </SurveyOption>
                    {surveyUsesLimit && (
                        <SurveyOption label="Completion conditions">
                            The survey will be stopped once <b>{survey.responses_limit}</b> responses are received.
                        </SurveyOption>
                    )}
                    {surveyUsesAdaptiveLimit && (
                        <SurveyOption label="Completion conditions">
                            <span>
                                Survey response collection is limited to receive <b>{survey.response_sampling_limit}</b>{' '}
                                responses every {survey.response_sampling_interval}{' '}
                                {survey.response_sampling_interval_type}
                                (s).
                            </span>
                        </SurveyOption>
                    )}
                    <SurveyOption label="Partial responses">
                        {survey.enable_partial_responses ? 'Enabled' : 'Disabled'}
                    </SurveyOption>
                    <LemonDivider />
                    <SurveyDisplaySummary id={survey.id} survey={survey} targetingFlagFilters={targetingFlagFilters} />
                </dl>
                {survey.type !== SurveyType.API ? (
                    <SurveyFormAppearance
                        previewPageIndex={selectedPageIndex || 0}
                        survey={survey}
                        handleSetSelectedPageIndex={(preview) => setSelectedPageIndex(preview)}
                    />
                ) : (
                    <div className="mt-2 space-y-2">
                        <div className="p-4 border rounded">
                            <div className="flex flex-row items-center w-full gap-1">
                                Learn how to set up API surveys{' '}
                                <Link
                                    data-attr="survey-doc-link"
                                    target="_blank"
                                    to="https://posthog.com/docs/surveys/implementing-custom-surveys"
                                    targetBlankIcon
                                >
                                    in the docs
                                </Link>
                            </div>
                        </div>

                        <SurveyAPIEditor survey={survey} />
                    </div>
                )}
            </div>
        </div>
    )
}
