import './SurveyView.scss'

import { TZLabel } from '@posthog/apps-common'
import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { useEffect, useState } from 'react'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ActivityScope, PropertyFilterType, PropertyOperator, Survey, SurveyQuestionType, SurveyType } from '~/types'

import { SURVEY_EVENT_NAME, SurveyQuestionLabel } from './constants'
import { SurveyDisplaySummary } from './Survey'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import {
    MultipleChoiceQuestionBarChart,
    NPSSurveyResultsBarChart,
    OpenTextViz,
    RatingQuestionBarChart,
    SingleChoiceQuestionPieChart,
    Summary,
} from './surveyViewViz'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, selectedPageIndex, targetingFlagFilters } = useValues(surveyLogic)
    const {
        editingSurvey,
        updateSurvey,
        launchSurvey,
        stopSurvey,
        archiveSurvey,
        resumeSurvey,
        setSelectedPageIndex,
        duplicateSurvey,
    } = useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')
    const showLinkedHogFunctions = useFeatureFlag('HOG_FUNCTIONS_LINKED')

    useEffect(() => {
        if (survey.start_date) {
            setTabKey('results')
        } else {
            setTabKey('overview')
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
                                                <LemonButton
                                                    data-attr="duplicate-survey"
                                                    fullWidth
                                                    onClick={duplicateSurvey}
                                                >
                                                    Duplicate
                                                </LemonButton>
                                                <LemonDivider />
                                            </>
                                            {survey.end_date && !survey.archived && (
                                                <LemonButton
                                                    data-attr="archive-survey"
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Archive this survey?',
                                                            content: (
                                                                <div className="text-sm text-muted">
                                                                    This action will remove the survey from your active
                                                                    surveys list. It can be restored at any time.
                                                                </div>
                                                            ),
                                                            primaryButton: {
                                                                children: 'Archive',
                                                                type: 'primary',
                                                                onClick: () => archiveSurvey(),
                                                                size: 'small',
                                                            },
                                                            secondaryButton: {
                                                                children: 'Cancel',
                                                                type: 'tertiary',
                                                                size: 'small',
                                                            },
                                                        })
                                                    }}
                                                    fullWidth
                                                >
                                                    Archive
                                                </LemonButton>
                                            )}
                                            <LemonButton
                                                status="danger"
                                                data-attr="delete-survey"
                                                fullWidth
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Delete this survey?',
                                                        content: (
                                                            <div className="text-sm text-muted">
                                                                This action cannot be undone. All survey data will be
                                                                permanently removed.
                                                            </div>
                                                        ),
                                                        primaryButton: {
                                                            children: 'Delete',
                                                            type: 'primary',
                                                            onClick: () => deleteSurvey(id),
                                                            size: 'small',
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                            type: 'tertiary',
                                                            size: 'small',
                                                        },
                                                    })
                                                }}
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
                                            LemonDialog.open({
                                                title: 'Launch this survey?',
                                                content: (
                                                    <div className="text-sm text-muted">
                                                        The survey will immediately start displaying to users matching
                                                        the display conditions.
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Launch',
                                                    type: 'primary',
                                                    onClick: () => launchSurvey(),
                                                    size: 'small',
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'tertiary',
                                                    size: 'small',
                                                },
                                            })
                                        }}
                                    >
                                        Launch
                                    </LemonButton>
                                ) : survey.end_date && !survey.archived ? (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Resume this survey?',
                                                content: (
                                                    <div className="text-sm text-muted">
                                                        Once resumed, the survey will be visible to your users again.
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Resume',
                                                    type: 'primary',
                                                    onClick: () => resumeSurvey(),
                                                    size: 'small',
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'tertiary',
                                                    size: 'small',
                                                },
                                            })
                                        }}
                                    >
                                        Resume
                                    </LemonButton>
                                ) : (
                                    !survey.archived && (
                                        <LemonButton
                                            data-attr="stop-survey"
                                            type="secondary"
                                            status="danger"
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Stop this survey?',
                                                    content: (
                                                        <div className="text-sm text-muted">
                                                            The survey will no longer be displayed to users.
                                                        </div>
                                                    ),
                                                    primaryButton: {
                                                        children: 'Stop',
                                                        type: 'primary',
                                                        onClick: () => stopSurvey(),
                                                        size: 'small',
                                                    },
                                                    secondaryButton: {
                                                        children: 'Cancel',
                                                        type: 'tertiary',
                                                        size: 'small',
                                                    },
                                                })
                                            }}
                                        >
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
                                                    <span>{SurveyQuestionLabel[survey.questions[0].type]}</span>
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
                                            <div className="flex flex-row gap-8">
                                                {survey.iteration_count &&
                                                survey.iteration_frequency_days &&
                                                survey.iteration_count > 0 &&
                                                survey.iteration_frequency_days > 0 ? (
                                                    <div className="flex flex-col">
                                                        <span className="card-secondary mt-4">Schedule</span>
                                                        <span>
                                                            Repeats every {survey.iteration_frequency_days}{' '}
                                                            {pluralize(
                                                                survey.iteration_frequency_days,
                                                                'day',
                                                                'days',
                                                                false
                                                            )}
                                                            , {survey.iteration_count}{' '}
                                                            {pluralize(survey.iteration_count, 'time', 'times', false)}
                                                        </span>
                                                    </div>
                                                ) : null}
                                            </div>
                                            {survey.responses_limit && (
                                                <>
                                                    <span className="card-secondary mt-4">Completion conditions</span>
                                                    <span>
                                                        The survey will be stopped once <b>{survey.responses_limit}</b>{' '}
                                                        responses are received.
                                                    </span>
                                                </>
                                            )}
                                            <LemonDivider />
                                            <SurveyDisplaySummary
                                                id={id}
                                                survey={survey}
                                                targetingFlagFilters={targetingFlagFilters}
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
                                                <div className="mt-6 max-w-72">
                                                    <SurveyFormAppearance
                                                        previewPageIndex={selectedPageIndex || 0}
                                                        survey={survey}
                                                        handleSetSelectedPageIndex={(preview) =>
                                                            setSelectedPageIndex(preview)
                                                        }
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
                            showLinkedHogFunctions
                                ? {
                                      key: 'notifications',
                                      label: 'Notifications',
                                      content: (
                                          <div>
                                              <p>Get notified whenever a survey result is submitted</p>
                                              <LinkedHogFunctions
                                                  subTemplateId="survey_response"
                                                  filters={{
                                                      events: [
                                                          {
                                                              id: 'survey sent',
                                                              type: 'events',
                                                              order: 0,
                                                              properties: [
                                                                  {
                                                                      key: '$survey_response',
                                                                      type: PropertyFilterType.Event,
                                                                      value: 'is_set',
                                                                      operator: PropertyOperator.IsSet,
                                                                  },
                                                                  {
                                                                      key: '$survey_id',
                                                                      type: PropertyFilterType.Event,
                                                                      value: id,
                                                                      operator: PropertyOperator.Exact,
                                                                  },
                                                              ],
                                                          },
                                                      ],
                                                  }}
                                              />
                                          </div>
                                      ),
                                  }
                                : null,
                            {
                                label: 'History',
                                key: 'History',
                                content: <ActivityLog scope={ActivityScope.SURVEY} id={survey.id} />,
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
        surveyRecurringNPSResults,
        surveyRecurringNPSResultsReady,
        surveySingleChoiceResults,
        surveySingleChoiceResultsReady,
        surveyMultipleChoiceResults,
        surveyMultipleChoiceResultsReady,
        surveyOpenTextResults,
        surveyOpenTextResultsReady,
        surveyNPSScore,
        surveyAsInsightURL,
    } = useValues(surveyLogic)

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
                                        <div className="font-semibold text-muted-alt mb-2">Latest NPS Score</div>
                                        <SurveyNPSResults survey={survey as Survey} />
                                    </>
                                )}

                                <RatingQuestionBarChart
                                    key={`survey-q-${i}`}
                                    surveyRatingResults={surveyRatingResults}
                                    surveyRatingResultsReady={surveyRatingResultsReady}
                                    questionIndex={i}
                                    iteration={survey.current_iteration}
                                />

                                {survey.iteration_count &&
                                    survey.iteration_count > 0 &&
                                    survey.current_iteration &&
                                    survey.current_iteration > 1 &&
                                    survey.iteration_start_dates &&
                                    survey.iteration_start_dates.length > 0 && (
                                        <NPSSurveyResultsBarChart
                                            key={`nps-survey-results-q-${i}`}
                                            surveyRecurringNPSResults={surveyRecurringNPSResults}
                                            surveyRecurringNPSResultsReady={surveyRecurringNPSResultsReady}
                                            iterationStartDates={survey.iteration_start_dates}
                                            currentIteration={survey.current_iteration}
                                            questionIndex={i}
                                        />
                                    )}
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
                    icon={<IconGraph />}
                    to={surveyAsInsightURL}
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
                                        value: ['9', '10'],
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
                                        value: ['7', '8'],
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
                                        value: ['0', '1', '2', '3', '4', '5', '6'],
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
                            {
                                type: PropertyFilterType.Event,
                                key: '$survey_iteration',
                                operator: PropertyOperator.Exact,
                                value: survey.current_iteration,
                            },
                        ],
                        trendsFilter: {
                            formula: '(A / (A+B+C) * 100) - (C / (A+B+C) * 100)',
                        },
                    },
                }}
            />
        </>
    )
}
