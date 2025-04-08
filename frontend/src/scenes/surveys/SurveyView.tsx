import './SurveyView.scss'

import { IconGraph, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, Spinner, Tooltip } from '@posthog/lemon-ui'
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
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyOverview } from 'scenes/surveys/SurveyOverview'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { ActivityScope, PropertyFilterType, PropertyOperator, Survey, SurveyQuestionType } from '~/types'

import {
    NPS_DETRACTOR_LABEL,
    NPS_DETRACTOR_VALUES,
    NPS_PASSIVE_LABEL,
    NPS_PASSIVE_VALUES,
    NPS_PROMOTER_LABEL,
    NPS_PROMOTER_VALUES,
    SURVEY_EVENT_NAME,
} from './constants'
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
                                            subTemplateId="survey-response"
                                            filters={{
                                                events: [
                                                    {
                                                        id: 'survey sent',
                                                        type: 'events',
                                                        order: 0,
                                                        properties: [
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

export function SurveyResult({ disableEventsTable }: { disableEventsTable?: boolean }): JSX.Element {
    const {
        survey,
        dataTableQuery,
        surveyLoading,
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
        isAnyResultsLoading,
    } = useValues(surveyLogic)

    return (
        <div className="deprecated-space-y-4">
            <SurveyResponseFilters />
            {isAnyResultsLoading && (
                <div className="flex gap-1">
                    <span className="text-sm text-secondary">Loading results...</span>
                    <Spinner />
                </div>
            )}
            <SurveyStatsSummary />
            {survey.questions.map((question, i) => {
                if (question.type === SurveyQuestionType.Rating) {
                    return (
                        <div key={`survey-q-${i}`} className="deprecated-space-y-2">
                            {question.scale === 10 && (
                                <SurveyNPSResults
                                    survey={survey as Survey}
                                    surveyNPSScore={surveyNPSScore}
                                    questionIndex={i}
                                    questionId={question.id}
                                />
                            )}

                            <RatingQuestionBarChart
                                surveyRatingResults={surveyRatingResults}
                                surveyRatingResultsReady={surveyRatingResultsReady}
                                questionIndex={i}
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
                        </div>
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
            <div className="max-w-40">
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
        event: SURVEY_EVENT_NAME,
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
                    <div className="flex items-center gap-2">
                        <div className="text-4xl font-bold">{surveyNPSScore}</div>
                    </div>
                    <div className="mb-2 font-semibold text-secondary">
                        <Tooltip
                            placement="bottom"
                            title="NPS Score is calculated by subtracting the percentage of detractors (0-6) from the percentage of promoters (9-10). Passives (7-8) are not included in the calculation. It can range from -100 to 100."
                        >
                            <IconInfo className="text-muted" />
                        </Tooltip>{' '}
                        Latest NPS Score
                    </div>
                    {npsBreakdown && (
                        <div className="mt-2 mb-4 deprecated-space-y-2">
                            <NPSStackedBar npsBreakdown={npsBreakdown} />
                        </div>
                    )}
                </>
            )}
            <div className="p-2 rounded deprecated-space-y-2 bg-surface-primary">
                <div className="flex items-center justify-between gap-2">
                    <h4 className="text-lg font-semibold">NPS Trend</h4>
                    <div className="flex items-center gap-2">
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
                            options={[
                                { value: 'hour', label: 'Hour' },
                                { value: 'day', label: 'Day' },
                                { value: 'week', label: 'Week' },
                                { value: 'month', label: 'Month' },
                            ]}
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
                                    key: '$survey_id',
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
