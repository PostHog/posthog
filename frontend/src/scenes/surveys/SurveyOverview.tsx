import { LemonDivider, Link } from '@posthog/lemon-ui'
import { id } from 'chartjs-plugin-trendline'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { SurveyQuestionLabel } from 'scenes/surveys/constants'
import { SurveyDisplaySummary } from 'scenes/surveys/Survey'
import { SurveyAPIEditor } from 'scenes/surveys/SurveyAPIEditor'
import { SurveyFormAppearance } from 'scenes/surveys/SurveyFormAppearance'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyQuestionType, SurveySchedule as SurveyScheduleEnum, SurveyType } from '~/types'

function SurveySchedule(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    if (survey.schedule === SurveyScheduleEnum.Recurring && survey.iteration_count && survey.iteration_frequency_days) {
        return (
            <>
                <span className="card-secondary">Schedule</span>
                <span>
                    Repeats every {survey.iteration_frequency_days}{' '}
                    {pluralize(survey.iteration_frequency_days, 'day', 'days', false)}, {survey.iteration_count}{' '}
                    {pluralize(survey.iteration_count, 'time', 'times', false)}
                </span>
            </>
        )
    }

    if (survey.schedule === SurveyScheduleEnum.Always) {
        return (
            <>
                <span className="card-secondary">Schedule</span>
                <span>Always</span>
            </>
        )
    }

    // Default case: survey is scheduled to run once
    return (
        <>
            <span className="card-secondary">Schedule</span>
            <span>Once</span>
        </>
    )
}

export function SurveyOverview(): JSX.Element {
    const { survey, selectedPageIndex, targetingFlagFilters } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const { surveyUsesLimit, surveyUsesAdaptiveLimit } = useValues(surveyLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="flex flex-row">
            <div className="flex flex-col w-full">
                <span className="mt-4 card-secondary">Display mode</span>
                <span>
                    {survey.type === SurveyType.API ? survey.type.toUpperCase() : capitalizeFirstLetter(survey.type)}
                </span>
                {survey.questions[0].question && (
                    <>
                        <span className="mt-4 card-secondary">Type</span>
                        <span>{SurveyQuestionLabel[survey.questions[0].type]}</span>
                        <span className="mt-4 card-secondary">
                            {pluralize(survey.questions.length, 'Question', 'Questions', false)}
                        </span>
                        {survey.questions.map((q, idx) => (
                            <li key={q.id ?? idx}>{q.question}</li>
                        ))}
                    </>
                )}
                {survey.questions[0].type === SurveyQuestionType.Link && (
                    <>
                        <span className="mt-4 card-secondary">Link url</span>
                        <span>{survey.questions[0].link}</span>
                    </>
                )}
                <div className="flex flex-row gap-8">
                    {survey.start_date && (
                        <div className="flex flex-col">
                            <span className="mt-4 card-secondary">Start date</span>
                            <TZLabel time={survey.start_date} />
                        </div>
                    )}
                    {survey.end_date && (
                        <div className="flex flex-col">
                            <span className="mt-4 card-secondary">End date</span>
                            <TZLabel time={survey.end_date} />
                        </div>
                    )}
                </div>
                <div className="flex flex-row gap-8">
                    <div className="flex flex-col mt-4">
                        <SurveySchedule />
                    </div>
                </div>
                {featureFlags[FEATURE_FLAGS.SURVEYS_PARTIAL_RESPONSES] && (
                    <div className="flex flex-col mt-4">
                        <span className="card-secondary">Store partial responses</span>
                        <span>{survey.store_partial_responses ? 'Yes' : 'No'}</span>
                    </div>
                )}
                {surveyUsesLimit && (
                    <>
                        <span className="mt-4 card-secondary">Completion conditions</span>
                        <span>
                            The survey will be stopped once <b>{survey.responses_limit}</b> responses are received.
                        </span>
                    </>
                )}
                {surveyUsesAdaptiveLimit && (
                    <>
                        <span className="mt-4 card-secondary">Completion conditions</span>
                        <span>
                            Survey response collection is limited to receive <b>{survey.response_sampling_limit}</b>{' '}
                            responses every {survey.response_sampling_interval} {survey.response_sampling_interval_type}
                            (s).
                        </span>
                    </>
                )}
                <LemonDivider />
                <SurveyDisplaySummary id={id} survey={survey} targetingFlagFilters={targetingFlagFilters} />
            </div>
            <div className="flex flex-col items-center w-full">
                {survey.type === SurveyType.API && (
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
                )}
                {survey.type !== SurveyType.API ? (
                    <div className="mt-6 max-w-72">
                        <SurveyFormAppearance
                            previewPageIndex={selectedPageIndex || 0}
                            survey={survey}
                            handleSetSelectedPageIndex={(preview) => setSelectedPageIndex(preview)}
                        />
                    </div>
                ) : (
                    <div className="mt-2">
                        <SurveyAPIEditor survey={survey} />
                    </div>
                )}
            </div>
        </div>
    )
}
