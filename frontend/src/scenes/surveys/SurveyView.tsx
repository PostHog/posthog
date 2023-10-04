import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { useState, useEffect } from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Query } from '~/queries/Query/Query'
import { surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { SurveyReleaseSummary } from './Survey'
import { SurveyAppearance } from './SurveyAppearance'
import {
    PropertyFilterType,
    PropertyOperator,
    RatingSurveyQuestion,
    Survey,
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
} from '~/types'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { NodeKind } from '~/queries/schema'
import { dayjs } from 'lib/dayjs'
import { defaultSurveyAppearance, SURVEY_EVENT_NAME } from './constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, surveyPlugin, showSurveyAppWarning } = useValues(surveyLogic)
    // TODO: survey results logic
    // const { surveyImpressionsCount, surveyStartedCount, surveyCompletedCount } = useValues(surveyResultsLogic)
    const { editingSurvey, updateSurvey, launchSurvey, stopSurvey, archiveSurvey, resumeSurvey } =
        useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { editPlugin } = useActions(pluginsLogic)

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
                        title={survey.name}
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
                                            <LemonButton status="danger" fullWidth onClick={() => deleteSurvey(id)}>
                                                Delete survey
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonDivider vertical />
                                {!survey.start_date ? (
                                    <LemonButton
                                        type="primary"
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
                    {!surveyLoading && showSurveyAppWarning && (
                        <LemonBanner type="error">
                            Surveys requires the{' '}
                            <a onClick={() => surveyPlugin?.id && editPlugin(surveyPlugin.id)}>survey app</a> to be
                            enabled. You also need to make sure you have the "opt_in_site_apps" setting in your PostHog
                            initialization code.
                        </LemonBanner>
                    )}
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
                                            <div className="border rounded p-4 w-full">
                                                {survey.type !== SurveyType.API ? (
                                                    showSurveyAppWarning && (
                                                        <div className="flex flex-col">
                                                            <div className="flex gap-2 items-start">
                                                                1. Add the following option to your PostHog instance:
                                                            </div>
                                                            <CodeSnippet language={Language.JavaScript} wrap>
                                                                {OPT_IN_SNIPPET}
                                                            </CodeSnippet>
                                                            <div className="flex items-center">
                                                                2.{' '}
                                                                <LemonButton
                                                                    onClick={() =>
                                                                        surveyPlugin?.id && editPlugin(surveyPlugin.id)
                                                                    }
                                                                >
                                                                    Enable and save the surveys app
                                                                </LemonButton>
                                                            </div>
                                                        </div>
                                                    )
                                                ) : (
                                                    <span className="font-medium">
                                                        See the documentation below on API survey setup.
                                                    </span>
                                                )}
                                                <div>
                                                    Need more information?{' '}
                                                    <a
                                                        data-attr="survey-doc-link"
                                                        target="_blank"
                                                        rel="noopener"
                                                        href="https://posthog.com/docs/surveys/manual"
                                                    >
                                                        Check the docs <IconOpenInNew />
                                                    </a>
                                                </div>
                                            </div>
                                            {survey.type !== SurveyType.API ? (
                                                <div className="mt-6">
                                                    <SurveyAppearance
                                                        type={survey.questions[0].type}
                                                        surveyQuestionItem={survey.questions[0]}
                                                        appearance={survey.appearance || defaultSurveyAppearance}
                                                        question={survey.questions[0].question}
                                                        description={survey.questions[0].description}
                                                        link={
                                                            survey.questions[0].type === SurveyQuestionType.Link
                                                                ? survey.questions[0].link
                                                                : undefined
                                                        }
                                                        readOnly={true}
                                                        onAppearanceChange={() => {}}
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
        surveyMetricsQueries,
        surveyRatingQuery,
        surveyMultipleChoiceQuery,
        currentQuestionIndexAndType,
    } = useValues(surveyLogic)
    const { setCurrentQuestionIndexAndType } = useActions(surveyLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            {surveyMetricsQueries && (
                <div className="flex flex-row gap-4 mb-4">
                    <div className="flex-1">
                        <Query query={surveyMetricsQueries.surveysShown} />
                    </div>
                    <div className="flex-1">
                        <Query query={surveyMetricsQueries.surveysDismissed} />
                    </div>
                </div>
            )}
            {survey.questions.length > 1 && (
                <div className="mb-4 max-w-80">
                    <LemonSelect
                        dropdownMatchSelectWidth
                        fullWidth
                        onChange={(idx) => {
                            setCurrentQuestionIndexAndType(idx, survey.questions[idx].type)
                        }}
                        options={[
                            ...survey.questions.map((q: SurveyQuestion, idx: number) => ({
                                label: q.question,
                                value: idx,
                            })),
                        ]}
                        value={currentQuestionIndexAndType.idx}
                    />
                </div>
            )}
            {currentQuestionIndexAndType.type === SurveyQuestionType.Rating && (
                <div className="mb-4">
                    <Query query={surveyRatingQuery} />
                    {featureFlags[FEATURE_FLAGS.SURVEY_NPS_RESULTS] &&
                        (survey.questions[currentQuestionIndexAndType.idx] as RatingSurveyQuestion).scale === 10 && (
                            <>
                                <LemonDivider className="my-4" />
                                <h2>NPS Score</h2>
                                <SurveyNPSResults survey={survey as Survey} />
                            </>
                        )}
                </div>
            )}
            {(currentQuestionIndexAndType.type === SurveyQuestionType.SingleChoice ||
                currentQuestionIndexAndType.type === SurveyQuestionType.MultipleChoice) && (
                <div className="mb-4">
                    <Query query={surveyMultipleChoiceQuery} />
                </div>
            )}
            {!disableEventsTable && (surveyLoading ? <LemonSkeleton /> : <Query query={dataTableQuery} />)}
        </>
    )
}

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`

function SurveyNPSResults({ survey }: { survey: Survey }): JSX.Element {
    return (
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
                                    value: [1, 2, 3, 4, 5, 6],
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
    )
}
