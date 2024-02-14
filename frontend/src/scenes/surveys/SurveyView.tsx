import './SurveyView.scss'

import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { InsightType, PropertyFilterType, PropertyOperator, Survey, SurveyQuestionType, SurveyType } from '~/types'

import { SURVEY_EVENT_NAME } from './constants'
import { SurveyReleaseSummary } from './Survey'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import {
    MultipleChoiceQuestionBarChart,
    OpenTextViz,
    RatingQuestionBarChart,
    SingleChoiceQuestionPieChart,
    Summary,
} from './surveyViewViz'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, selectedQuestion } = useValues(surveyLogic)
    const { editingSurvey, updateSurvey, launchSurvey, stopSurvey, archiveSurvey, resumeSurvey, setSelectedQuestion } =
        useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')

    useEffect(() => {
        if (survey.start_date) {
            setTabKey('results')
        }
    }, [survey.start_date])

    return (
        <div>
            {surveyLoading ? (
                <LemonSkeleton />
            ) : (
                <>
                    <PageHeader
                        buttons={
                            <div className="flex items-center gap-2">
                                <More
                                    overlay={
                                        <>
                                            <>
                                                <LemonButton
                                                    data-attr="edit-survey"
                                                    fullWidth
                                                    onClick={() => editingSurvey(true)}
                                                >
                                                    Edit
                                                </LemonButton>
                                                <LemonDivider />
                                            </>
                                            {survey.end_date && !survey.archived && (
                                                <LemonButton onClick={() => archiveSurvey()} fullWidth>
                                                    Archive
                                                </LemonButton>
                                            )}
                                            <LemonButton
                                                status="danger"
                                                data-attr="delete-survey"
                                                fullWidth
                                                onClick={() => deleteSurvey(id)}
                                            >
                                                Delete survey
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonDivider vertical />
                                {!survey.start_date ? (
                                    <LemonButton
                                        type="primary"
                                        data-attr="launch-survey"
                                        onClick={() => {
                                            launchSurvey()
                                        }}
                                    >
                                        Launch
                                    </LemonButton>
                                ) : survey.end_date && !survey.archived ? (
                                    <LemonButton type="secondary" onClick={() => resumeSurvey()}>
                                        Resume
                                    </LemonButton>
                                ) : (
                                    !survey.archived && (
                                        <LemonButton type="secondary" status="danger" onClick={() => stopSurvey()}>
                                            Stop
                                        </LemonButton>
                                    )
                                )}
                            </div>
                        }
                        caption={
                            <>
                                {survey && !!survey.description && (
                                    <EditableField
                                        multiline
                                        name="description"
                                        markdown
                                        value={survey.description || ''}
                                        placeholder="Description (optional)"
                                        onSave={(value) => updateSurvey({ id: id, description: value })}
                                        saveOnBlur={true}
                                        compactButtons
                                    />
                                )}
                            </>
                        }
                    />
                    <LemonTabs
                        activeKey={tabKey}
                        onChange={(key) => setTabKey(key)}
                        tabs={[
                            survey.start_date
                                ? {
                                      content: (
                                          <div>
                                              <SurveyResult />
                                          </div>
                                      ),
                                      key: 'results',
                                      label: 'Results',
                                  }
                                : null,
                            {
                                content: (
                                    <div className="flex flex-row">
                                        <div className="flex flex-col w-full">
                                            <span className="card-secondary mt-4">Display mode</span>
                                            <span>
                                                {survey.type === SurveyType.API
                                                    ? survey.type.toUpperCase()
                                                    : capitalizeFirstLetter(survey.type)}
                                            </span>
                                            {survey.questions[0].question && (
                                                <>
                                                    <span className="card-secondary mt-4">Type</span>
                                                    <span>
                                                        {survey.questions.length > 1
                                                            ? 'Multiple questions'
                                                            : capitalizeFirstLetter(survey.questions[0].type)}
                                                    </span>
                                                    <span className="card-secondary mt-4">
                                                        {pluralize(
                                                            survey.questions.length,
                                                            'Question',
                                                            'Questions',
                                                            false
                                                        )}
                                                    </span>
                                                    {survey.questions.map((q, idx) => (
                                                        <li key={idx}>{q.question}</li>
                                                    ))}
                                                </>
                                            )}
                                            {survey.questions[0].type === SurveyQuestionType.Link && (
                                                <>
                                                    <span className="card-secondary mt-4">Link url</span>
                                                    <span>{survey.questions[0].link}</span>
                                                </>
                                            )}
                                            <div className="flex flex-row gap-8">
                                                {survey.start_date && (
                                                    <div className="flex flex-col">
                                                        <span className="card-secondary mt-4">Start date</span>
                                                        <TZLabel time={survey.start_date} />
                                                    </div>
                                                )}
                                                {survey.end_date && (
                                                    <div className="flex flex-col">
                                                        <span className="card-secondary mt-4">End date</span>
                                                        <TZLabel time={survey.end_date} />
                                                    </div>
                                                )}
                                            </div>
                                            <LemonDivider />
                                            <SurveyReleaseSummary
                                                id={id}
                                                survey={survey}
                                                hasTargetingFlag={!!survey.targeting_flag}
                                            />
                                        </div>
                                        <div className="w-full flex flex-col items-center">
                                            {survey.type === SurveyType.API && (
                                                <div className="border rounded p-4">
                                                    <div className="w-full flex flex-row gap-1 items-center">
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
                                                <div className="mt-6 max-w-80">
                                                    <SurveyFormAppearance
                                                        activePreview={selectedQuestion || 0}
                                                        survey={survey}
                                                        setActivePreview={(preview) => setSelectedQuestion(preview)}
                                                    />
                                                </div>
                                            ) : (
                                                <div className="mt-2">
                                                    <SurveyAPIEditor survey={survey} />
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ),
                                key: 'overview',
                                label: 'Overview',
                            },
                        ]}
                    />
                </>
            )}
        </div>
    )
}

export function SurveyResult({ disableEventsTable }: { disableEventsTable?: boolean }): JSX.Element {
    const {
        survey,
        dataTableQuery,
        surveyLoading,
        surveyUserStats,
        surveyUserStatsLoading,
        surveyRatingResults,
        surveyRatingResultsReady,
        surveySingleChoiceResults,
        surveySingleChoiceResultsReady,
        surveyMultipleChoiceResults,
        surveyMultipleChoiceResultsReady,
        surveyOpenTextResults,
        surveyOpenTextResultsReady,
        surveyNPSScore,
    } = useValues(surveyLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <>
                <Summary surveyUserStatsLoading={surveyUserStatsLoading} surveyUserStats={surveyUserStats} />
                {survey.questions.map((question, i) => {
                    if (question.type === SurveyQuestionType.Rating) {
                        return (
                            <>
                                {question.scale === 10 && (
                                    <>
                                        <div className="text-4xl font-bold">{surveyNPSScore}</div>
                                        <div className="font-semibold text-muted-alt mb-2">Total NPS Score</div>
                                        {featureFlags[FEATURE_FLAGS.SURVEYS_RESULTS_VISUALIZATIONS] && (
                                            // TODO: rework this to show nps scores over time
                                            <SurveyNPSResults survey={survey as Survey} />
                                        )}
                                    </>
                                )}
                                <RatingQuestionBarChart
                                    key={`survey-q-${i}`}
                                    surveyRatingResults={surveyRatingResults}
                                    surveyRatingResultsReady={surveyRatingResultsReady}
                                    questionIndex={i}
                                />
                            </>
                        )
                    } else if (question.type === SurveyQuestionType.SingleChoice) {
                        return (
                            <SingleChoiceQuestionPieChart
                                key={`survey-q-${i}`}
                                surveySingleChoiceResults={surveySingleChoiceResults}
                                surveySingleChoiceResultsReady={surveySingleChoiceResultsReady}
                                questionIndex={i}
                            />
                        )
                    } else if (question.type === SurveyQuestionType.MultipleChoice) {
                        return (
                            <MultipleChoiceQuestionBarChart
                                key={`survey-q-${i}`}
                                surveyMultipleChoiceResults={surveyMultipleChoiceResults}
                                surveyMultipleChoiceResultsReady={surveyMultipleChoiceResultsReady}
                                questionIndex={i}
                            />
                        )
                    } else if (question.type === SurveyQuestionType.Open) {
                        return (
                            <OpenTextViz
                                key={`survey-q-${i}`}
                                surveyOpenTextResults={surveyOpenTextResults}
                                surveyOpenTextResultsReady={surveyOpenTextResultsReady}
                                questionIndex={i}
                            />
                        )
                    }
                })}
            </>
            <div className="max-w-40 mb-4">
                <LemonButton
                    type="primary"
                    data-attr="survey-results-explore"
                    to={urls.insightNew({
                        insight: InsightType.TRENDS,
                        events: [
                            { id: 'survey sent', name: 'survey sent', type: 'events' },
                            { id: 'survey shown', name: 'survey shown', type: 'events' },
                            { id: 'survey dismissed', name: 'survey dismissed', type: 'events' },
                        ],
                        properties: [
                            {
                                key: '$survey_id',
                                value: survey.id,
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    })}
                >
                    Explore results
                </LemonButton>
            </div>
            {!disableEventsTable && (surveyLoading ? <LemonSkeleton /> : <Query query={dataTableQuery} />)}
        </>
    )
}

function SurveyNPSResults({ survey }: { survey: Survey }): JSX.Element {
    return (
        <>
            <Query
                query={{
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        dateRange: {
                            date_from: dayjs(survey.created_at).format('YYYY-MM-DD'),
                            date_to: survey.end_date
                                ? dayjs(survey.end_date).format('YYYY-MM-DD')
                                : dayjs().add(1, 'day').format('YYYY-MM-DD'),
                        },
                        series: [
                            {
                                event: SURVEY_EVENT_NAME,
                                kind: NodeKind.EventsNode,
                                custom_name: 'Promoters',
                                properties: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$survey_response',
                                        operator: PropertyOperator.Exact,
                                        value: [9, 10],
                                    },
                                ],
                            },
                            {
                                event: SURVEY_EVENT_NAME,
                                kind: NodeKind.EventsNode,
                                custom_name: 'Passives',
                                properties: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$survey_response',
                                        operator: PropertyOperator.Exact,
                                        value: [7, 8],
                                    },
                                ],
                            },
                            {
                                event: SURVEY_EVENT_NAME,
                                kind: NodeKind.EventsNode,
                                custom_name: 'Detractors',
                                properties: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$survey_response',
                                        operator: PropertyOperator.Exact,
                                        value: [0, 1, 2, 3, 4, 5, 6],
                                    },
                                ],
                            },
                        ],
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$survey_id',
                                operator: PropertyOperator.Exact,
                                value: survey.id,
                            },
                        ],
                        trendsFilter: {
                            formula: '(A / (A+B+C) * 100) - (C / (A+B+C)* 100)',
                        },
                    },
                }}
            />
        </>
    )
}
