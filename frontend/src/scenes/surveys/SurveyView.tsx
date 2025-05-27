import './SurveyView.scss'

import { IconGraph, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, lemonToast, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect, useState } from 'react'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { SurveyOverview } from 'scenes/surveys/SurveyOverview'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    ActivityScope,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import {
    LOADING_SURVEY_RESULTS_TOAST_ID,
    NPS_DETRACTOR_LABEL,
    NPS_DETRACTOR_VALUES,
    NPS_PASSIVE_LABEL,
    NPS_PASSIVE_VALUES,
    NPS_PROMOTER_LABEL,
    NPS_PROMOTER_VALUES,
} from './constants'
import { SurveysDisabledBanner } from './SurveySettings'
import {
    MultipleChoiceQuestionBarChart,
    NPSStackedBar,
    NPSSurveyResultsBarChart,
    OpenTextViz,
    RatingQuestionBarChart,
    SingleChoiceQuestionPieChart,
} from './surveyViewViz'
export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading } = useValues(surveyLogic)
    const { editingSurvey, updateSurvey, launchSurvey, stopSurvey, archiveSurvey, resumeSurvey, duplicateSurvey } =
        useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { showSurveysDisabledBanner } = useValues(surveysLogic)

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')

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
                            <div className="flex gap-2 items-center">
                                <LemonButton size="small" type="secondary" id="surveys-page-feedback-button">
                                    Have any questions or feedback?
                                </LemonButton>
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
                                                                <div className="text-sm text-secondary">
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
                                                            <div className="text-sm text-secondary">
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
                                        disabledReason={
                                            showSurveysDisabledBanner && survey.type !== SurveyType.API
                                                ? 'Please enable surveys in the banner below before launching'
                                                : undefined
                                        }
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Launch this survey?',
                                                content: (
                                                    <div className="text-sm text-secondary">
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
                                                    <div className="text-sm text-secondary">
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
                                                        <div className="text-sm text-secondary">
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
                    <SurveysDisabledBanner />
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
                                content: <SurveyOverview />,
                                key: 'overview',
                                label: 'Overview',
                            },
                            {
                                key: 'notifications',
                                label: 'Notifications',
                                content: (
                                    <div>
                                        <p>Get notified whenever a survey result is submitted</p>
                                        <LinkedHogFunctions
                                            logicKey="survey"
                                            type="destination"
                                            subTemplateIds={['survey-response']}
                                            filters={{
                                                events: [
                                                    {
                                                        id: SurveyEventName.SENT,
                                                        type: 'events',
                                                        properties: [
                                                            {
                                                                key: SurveyEventProperties.SURVEY_ID,
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
                            },
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

function SurveyResponsesByQuestionV2(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    return (
        <div className="flex flex-col gap-2">
            {survey.questions.map((question, i) => {
                if (!question.id || question.type === SurveyQuestionType.Link) {
                    return null
                }
                return (
                    <div key={question.id} className="flex flex-col gap-2">
                        <SurveyQuestionVisualization question={question} questionIndex={i} />
                        <LemonDivider />
                    </div>
                )
            })}
        </div>
    )
}

export function SurveyResponsesByQuestion(): JSX.Element {
    const {
        survey,
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
    } = useValues(surveyLogic)

    return (
        <div className="flex flex-col gap-1">
            {survey.questions.map((question, i) => {
                if (question.type === SurveyQuestionType.Rating) {
                    return (
                        <div key={question.id || `survey-q-${i}`} className="flex flex-col gap-2">
                            <RatingQuestionBarChart
                                surveyRatingResults={surveyRatingResults}
                                surveyRatingResultsReady={surveyRatingResultsReady}
                                questionIndex={i}
                            />
                            {question.scale === 10 && (
                                <SurveyNPSResults
                                    survey={survey as Survey}
                                    surveyNPSScore={surveyNPSScore}
                                    questionIndex={i}
                                    questionId={question.id}
                                />
                            )}

                            {!!survey.iteration_count &&
                                survey.current_iteration &&
                                survey.current_iteration > 1 &&
                                !!survey.iteration_start_dates?.length && (
                                    <NPSSurveyResultsBarChart
                                        surveyRecurringNPSResults={surveyRecurringNPSResults}
                                        surveyRecurringNPSResultsReady={surveyRecurringNPSResultsReady}
                                        iterationStartDates={survey.iteration_start_dates}
                                        currentIteration={survey.current_iteration}
                                        questionIndex={i}
                                    />
                                )}

                            <LemonDivider />
                        </div>
                    )
                } else if (question.type === SurveyQuestionType.SingleChoice) {
                    return (
                        <div key={question.id || `survey-q-${i}`} className="flex flex-col gap-2">
                            <SingleChoiceQuestionPieChart
                                surveySingleChoiceResults={surveySingleChoiceResults}
                                surveySingleChoiceResultsReady={surveySingleChoiceResultsReady}
                                questionIndex={i}
                            />
                            <LemonDivider />
                        </div>
                    )
                } else if (question.type === SurveyQuestionType.MultipleChoice) {
                    return (
                        <div key={question.id || `survey-q-${i}`} className="flex flex-col gap-2">
                            <MultipleChoiceQuestionBarChart
                                surveyMultipleChoiceResults={surveyMultipleChoiceResults}
                                surveyMultipleChoiceResultsReady={surveyMultipleChoiceResultsReady}
                                questionIndex={i}
                            />
                            <LemonDivider />
                        </div>
                    )
                } else if (question.type === SurveyQuestionType.Open) {
                    return (
                        <div key={question.id || `survey-q-${i}`} className="flex flex-col gap-2">
                            <OpenTextViz
                                surveyOpenTextResults={surveyOpenTextResults}
                                surveyOpenTextResultsReady={surveyOpenTextResultsReady}
                                questionIndex={i}
                            />
                            <LemonDivider />
                        </div>
                    )
                }
            })}
        </div>
    )
}

export function SurveyResult({ disableEventsTable }: { disableEventsTable?: boolean }): JSX.Element {
    const {
        dataTableQuery,
        surveyLoading,
        surveyAsInsightURL,
        isAnyResultsLoading,
        processedSurveyStats,
        isNewQuestionVizEnabled,
    } = useValues(surveyLogic)

    const atLeastOneResonse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count

    if (isAnyResultsLoading) {
        lemonToast.info('Loading survey results...', {
            toastId: LOADING_SURVEY_RESULTS_TOAST_ID,
            hideProgressBar: true,
            icon: <Spinner />,
            autoClose: false,
            closeOnClick: false,
            closeButton: false,
            draggable: false,
            pauseOnHover: false,
            pauseOnFocusLoss: false,
        })
    } else {
        lemonToast.dismiss(LOADING_SURVEY_RESULTS_TOAST_ID)
    }

    return (
        <div className="deprecated-space-y-4">
            <SurveyResponseFilters />
            <SurveyStatsSummary />
            {isAnyResultsLoading || atLeastOneResonse ? (
                <>
                    {isNewQuestionVizEnabled ? <SurveyResponsesByQuestionV2 /> : <SurveyResponsesByQuestion />}
                    <LemonButton
                        type="primary"
                        data-attr="survey-results-explore"
                        icon={<IconGraph />}
                        to={surveyAsInsightURL}
                        className="max-w-40"
                    >
                        Explore results
                    </LemonButton>
                    {!disableEventsTable &&
                        (surveyLoading ? (
                            <LemonSkeleton />
                        ) : (
                            <div className="survey-table-results">
                                <Query query={dataTableQuery} />
                            </div>
                        ))}
                </>
            ) : (
                <SurveyNoResponsesBanner type="survey" />
            )}
        </div>
    )
}

function createNPSTrendSeries(
    values: string[],
    label: string,
    questionIndex: number,
    questionId?: string
): {
    event: string
    kind: NodeKind.EventsNode
    custom_name: string
    properties: Array<{
        type: PropertyFilterType.HogQL
        key: string
    }>
} {
    return {
        event: SurveyEventName.SENT,
        kind: NodeKind.EventsNode,
        custom_name: label,
        properties: [
            {
                type: PropertyFilterType.HogQL,
                key: `getSurveyResponse(${questionIndex}, ${questionId ? `'${questionId}'` : ''}) in (${values.join(
                    ','
                )})`,
            },
        ],
    }
}

function SurveyNPSResults({
    survey,
    surveyNPSScore,
    questionIndex,
    questionId,
}: {
    survey: Survey
    surveyNPSScore?: string | null
    questionIndex: number
    questionId?: string
}): JSX.Element {
    const { dateRange, interval, compareFilter, defaultInterval, npsBreakdown } = useValues(surveyLogic)
    const { setDateRange, setInterval, setCompareFilter } = useActions(surveyLogic)

    return (
        <div>
            {surveyNPSScore && (
                <>
                    <div className="flex gap-2 items-center">
                        <div className="text-4xl font-bold">{surveyNPSScore}</div>
                    </div>
                    <div className="mb-2 font-semibold text-secondary">
                        <Tooltip
                            placement="bottom"
                            title="NPS Score is calculated by subtracting the percentage of detractors (0-6) from the percentage of promoters (9-10). Passives (7-8) are not included in the calculation. It can range from -100 to 100."
                        >
                            <IconInfo className="text-muted mr-1" />
                            Latest NPS Score
                        </Tooltip>
                    </div>
                    {npsBreakdown && (
                        <div className="mt-2 mb-4 deprecated-space-y-2">
                            <NPSStackedBar npsBreakdown={npsBreakdown} />
                        </div>
                    )}
                </>
            )}
            <div className="p-2 rounded deprecated-space-y-2 bg-surface-primary">
                <div className="flex gap-2 justify-between items-center">
                    <h4 className="text-lg font-semibold">NPS Trend</h4>
                    <div className="flex gap-2 items-center">
                        <DateFilter
                            dateFrom={dateRange?.date_from ?? undefined}
                            dateTo={dateRange?.date_to ?? undefined}
                            onChange={(fromDate, toDate) =>
                                setDateRange({
                                    date_from: fromDate,
                                    date_to: toDate,
                                })
                            }
                        />
                        <span>grouped by</span>
                        <IntervalFilterStandalone
                            interval={interval ?? defaultInterval}
                            onIntervalChange={setInterval}
                        />
                        <CompareFilter
                            compareFilter={compareFilter}
                            updateCompareFilter={(compareFilter) => setCompareFilter(compareFilter)}
                        />
                    </div>
                </div>
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            interval: interval ?? defaultInterval,
                            compareFilter: compareFilter,
                            dateRange: dateRange ?? {
                                date_from: dayjs(survey.created_at).format('YYYY-MM-DD'),
                                date_to: survey.end_date
                                    ? dayjs(survey.end_date).format('YYYY-MM-DD')
                                    : dayjs().add(1, 'day').format('YYYY-MM-DD'),
                            },
                            series: [
                                createNPSTrendSeries(
                                    NPS_PROMOTER_VALUES,
                                    NPS_PROMOTER_LABEL,
                                    questionIndex,
                                    questionId
                                ),
                                createNPSTrendSeries(NPS_PASSIVE_VALUES, NPS_PASSIVE_LABEL, questionIndex, questionId),
                                createNPSTrendSeries(
                                    NPS_DETRACTOR_VALUES,
                                    NPS_DETRACTOR_LABEL,
                                    questionIndex,
                                    questionId
                                ),
                            ],
                            properties: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: SurveyEventProperties.SURVEY_ID,
                                    operator: PropertyOperator.Exact,
                                    value: survey.id,
                                },
                            ],
                            trendsFilter: {
                                formula: '(A / (A+B+C) * 100) - (C / (A+B+C) * 100)',
                                display: 'ActionsBar',
                            },
                        },
                    }}
                    readOnly
                />
            </div>
        </div>
    )
}
