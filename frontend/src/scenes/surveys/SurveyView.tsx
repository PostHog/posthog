import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDivider, LemonCollapse, LemonCheckbox, Link } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState, useEffect } from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { urls } from 'scenes/urls'
import { Query } from '~/queries/Query/Query'
import { defaultSurveyAppearance, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { SurveyReleaseSummary } from './Survey'
import { SurveyAppearance } from './SurveyAppearance'
import { SurveyQuestionType } from '~/types'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, dataTableQuery, surveyLoading, surveyPlugin, surveyMetricsQueries } = useValues(surveyLogic)
    // TODO: survey results logic
    // const { surveyImpressionsCount, surveyStartedCount, surveyCompletedCount } = useValues(surveyResultsLogic)
    const { editingSurvey, updateSurvey, launchSurvey, stopSurvey, archiveSurvey } = useActions(surveyLogic)
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
                                            {!survey.end_date && (
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
                                            )}
                                            <LemonButton status="danger" onClick={() => deleteSurvey(id)}>
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
                                    <LemonButton type="secondary" onClick={() => archiveSurvey()}>
                                        Archive
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
                            {
                                content: (
                                    <div className="flex flex-row">
                                        <div className="flex flex-col w-full">
                                            <span className="card-secondary mt-4">Type</span>
                                            <span>{capitalizeFirstLetter(survey.questions[0].type)}</span>
                                            <span className="card-secondary mt-4">Question</span>
                                            {survey.questions.map((q, idx) => (
                                                <span key={idx}>{q.question}</span>
                                            ))}
                                            {survey.questions[0].type === SurveyQuestionType.Link && (
                                                <>
                                                    <span className="card-secondary mt-4">Link url</span>
                                                    <span>{survey.questions[0].link}</span>
                                                </>
                                            )}

                                            <span className="card-secondary mt-4">Linked feature flag</span>
                                            {survey.linked_flag ? (
                                                <Link to={urls.featureFlag(survey.linked_flag.id)}>
                                                    {survey.linked_flag.key}
                                                </Link>
                                            ) : (
                                                <span>None</span>
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
                                            <span className="card-secondary">Release summary</span>
                                            <SurveyReleaseSummary
                                                id={id}
                                                survey={survey}
                                                targetingFlagFilters={survey.targeting_flag?.filters}
                                            />
                                        </div>
                                        <div className="w-full flex flex-col items-center">
                                            <LemonCollapse
                                                className="w-full"
                                                panels={[
                                                    {
                                                        key: '1',
                                                        header: 'Survey setup help',
                                                        content: (
                                                            <div>
                                                                <div className="flex flex-col">
                                                                    <span className="font-medium mb-2">
                                                                        Option 1: Enable the surveys app (recommended)
                                                                    </span>
                                                                    <div className="flex gap-2 items-start">
                                                                        <LemonCheckbox /> Add the following option to
                                                                        your PostHog instance:
                                                                    </div>
                                                                    <CodeSnippet language={Language.JavaScript} wrap>
                                                                        {OPT_IN_SNIPPET}
                                                                    </CodeSnippet>
                                                                    <div className="flex items-center gap-1">
                                                                        <LemonCheckbox />{' '}
                                                                        <LemonButton
                                                                            onClick={() =>
                                                                                surveyPlugin?.id &&
                                                                                editPlugin(surveyPlugin.id)
                                                                            }
                                                                        >
                                                                            Enable and save the surveys app
                                                                        </LemonButton>
                                                                    </div>
                                                                </div>
                                                                <div className="flex flex-col mt-3">
                                                                    <span className="font-medium">
                                                                        Option 2: Create your own custom survey UI with
                                                                        our headless API
                                                                    </span>
                                                                    <Link
                                                                        to="https://posthog.com/docs/surveys/manual"
                                                                        target="_blank"
                                                                    >
                                                                        See documentation
                                                                    </Link>
                                                                </div>
                                                            </div>
                                                        ),
                                                    },
                                                ]}
                                            />
                                            <div className="mt-6">
                                                <SurveyAppearance
                                                    type={survey.questions[0].type}
                                                    appearance={survey.appearance || defaultSurveyAppearance}
                                                    question={survey.questions[0].question}
                                                    description={survey.questions[0].description}
                                                    link={survey.questions[0].link}
                                                    readOnly={true}
                                                    onAppearanceChange={() => {}}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                ),
                                key: 'overview',
                                label: 'Overview',
                            },
                            survey.start_date
                                ? {
                                      content: (
                                          <div>
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
                                              {surveyLoading ? <LemonSkeleton /> : <Query query={dataTableQuery} />}
                                          </div>
                                      ),
                                      key: 'results',
                                      label: 'Results',
                                  }
                                : null,
                        ]}
                    />
                </>
            )}
        </div>
    )
}

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`
