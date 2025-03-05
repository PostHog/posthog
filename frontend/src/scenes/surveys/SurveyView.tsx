import './SurveyView.scss'

import { IconGraph, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, Link, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { useEffect, useState } from 'react'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { getResponseFieldWithId } from 'scenes/surveys/utils'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    ActivityScope,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyQuestionType,
    SurveySchedule as SurveyScheduleEnum,
    SurveyType,
} from '~/types'

import { NPS_DETRACTOR_LABEL, NPS_PASSIVE_LABEL, SURVEY_EVENT_NAME, SurveyQuestionLabel } from './constants'
import { SurveyDisplaySummary } from './Survey'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import {
    MultipleChoiceQuestionBarChart,
    NPSStackedBar,
    NPSSurveyResultsBarChart,
    OpenTextViz,
    RatingQuestionBarChart,
    SingleChoiceQuestionPieChart,
    Summary,
} from './surveyViewViz'

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
    const { surveyUsesLimit, surveyUsesAdaptiveLimit } = useValues(surveyLogic)
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
                                content: (
                                    <div className="flex flex-row">
                                        <div className="flex flex-col w-full">
                                            <span className="mt-4 card-secondary">Display mode</span>
                                            <span>
                                                {survey.type === SurveyType.API
                                                    ? survey.type.toUpperCase()
                                                    : capitalizeFirstLetter(survey.type)}
                                            </span>
                                            {survey.questions[0].question && (
                                                <>
                                                    <span className="mt-4 card-secondary">Type</span>
                                                    <span>{SurveyQuestionLabel[survey.questions[0].type]}</span>
                                                    <span className="mt-4 card-secondary">
                                                        {pluralize(
                                                            survey.questions.length,
                                                            'Question',
                                                            'Questions',
                                                            false
                                                        )}
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
                                            {surveyUsesLimit && (
                                                <>
                                                    <span className="mt-4 card-secondary">Completion conditions</span>
                                                    <span>
                                                        The survey will be stopped once <b>{survey.responses_limit}</b>{' '}
                                                        responses are received.
                                                    </span>
                                                </>
                                            )}
                                            {surveyUsesAdaptiveLimit && (
                                                <>
                                                    <span className="mt-4 card-secondary">Completion conditions</span>
                                                    <span>
                                                        Survey response collection is limited to receive{' '}
                                                        <b>{survey.response_sampling_limit}</b> responses every{' '}
                                                        {survey.response_sampling_interval}{' '}
                                                        {survey.response_sampling_interval_type}(s).
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
            <Summary surveyUserStatsLoading={surveyUserStatsLoading} surveyUserStats={surveyUserStats} />
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
                        <div className="deprecated-space-y-2 mt-2 mb-4">
                            <NPSStackedBar npsBreakdown={npsBreakdown} />
                        </div>
                    )}
                </>
            )}
            <div className="deprecated-space-y-2 bg-surface-primary p-2 rounded">
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
                                {
                                    event: SURVEY_EVENT_NAME,
                                    kind: NodeKind.EventsNode,
                                    custom_name: NPS_PASSIVE_LABEL,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: getResponseFieldWithId(questionIndex, questionId).indexBasedKey,
                                            operator: PropertyOperator.Exact,
                                            value: ['9', '10'],
                                        },
                                    ],
                                },
                                {
                                    event: SURVEY_EVENT_NAME,
                                    kind: NodeKind.EventsNode,
                                    custom_name: NPS_PASSIVE_LABEL,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: getResponseFieldWithId(questionIndex, questionId).idBasedKey,
                                            operator: PropertyOperator.Exact,
                                            value: ['9', '10'],
                                        },
                                    ],
                                },
                                {
                                    event: SURVEY_EVENT_NAME,
                                    kind: NodeKind.EventsNode,
                                    custom_name: NPS_PASSIVE_LABEL,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: getResponseFieldWithId(questionIndex, questionId).indexBasedKey,
                                            operator: PropertyOperator.Exact,
                                            value: ['7', '8'],
                                        },
                                    ],
                                },
                                {
                                    event: SURVEY_EVENT_NAME,
                                    kind: NodeKind.EventsNode,
                                    custom_name: NPS_PASSIVE_LABEL,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: getResponseFieldWithId(questionIndex, questionId).idBasedKey,
                                            operator: PropertyOperator.Exact,
                                            value: ['7', '8'],
                                        },
                                    ],
                                },
                                {
                                    event: SURVEY_EVENT_NAME,
                                    kind: NodeKind.EventsNode,
                                    custom_name: NPS_DETRACTOR_LABEL,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: getResponseFieldWithId(questionIndex, questionId).indexBasedKey,
                                            operator: PropertyOperator.Exact,
                                            value: ['0', '1', '2', '3', '4', '5', '6'],
                                        },
                                    ],
                                },
                                {
                                    event: SURVEY_EVENT_NAME,
                                    kind: NodeKind.EventsNode,
                                    custom_name: NPS_DETRACTOR_LABEL,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: getResponseFieldWithId(questionIndex, questionId).idBasedKey,
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
                            ],
                            trendsFilter: {
                                /**
                                 * We now have two response fields to consider: both index-based and id-based.
                                 * So we need to sum up the promoters and detractors from both fields.
                                 * A+B is promoters
                                 * C+D is passives
                                 * E+F is detractors
                                 *
                                 * A+B+C+D+E+F is total responses
                                 *
                                 * The old formula is formula: '(A / (A+B+C) * 100) - (C / (A+B+C) * 100)',
                                 *
                                 * The new formula is formula: '((A+B) / (A+B+C+D+E+F) * 100) - ((E+F) / (A+B+C+D+E+F) * 100)',
                                 */
                                formula: '((A+B) / (A+B+C+D+E+F) * 100) - ((E+F) / (A+B+C+D+E+F) * 100)',
                                display: 'ActionsBar',
                            },
                        },
                    }}
                />
            </div>
        </div>
    )
}
