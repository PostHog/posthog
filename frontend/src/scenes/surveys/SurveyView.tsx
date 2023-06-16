import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDivider, LemonCollapse, LemonCheckbox, LemonModal, Link } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconSubArrowRight } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { SurveyType } from 'posthog-js'
import { useState, useEffect } from 'react'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { urls } from 'scenes/urls'
import { cohortsModel } from '~/models/cohortsModel'
import { Query } from '~/queries/Query/Query'
import { FilterLogicalOperator } from '~/types'
import { surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, dataTableQuery, surveyLoading, surveyPlugin, installingPlugin } = useValues(surveyLogic)
    // TODO: survey results logic
    // const { surveyImpressionsCount, surveyStartedCount, surveyCompletedCount } = useValues(surveyResultsLogic)
    const { editingSurvey, updateSurvey, launchSurvey, stopSurvey, archiveSurvey, installSurveyPlugin } =
        useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { cohortsById } = useValues(cohortsModel)
    const { editPlugin } = useActions(pluginsLogic)
    const [setupModalIsOpen, setSetupModalIsOpen] = useState(false)

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
                                            if (!surveyPlugin && !survey.conditions?.is_headless) {
                                                setSetupModalIsOpen(true)
                                            } else {
                                                launchSurvey()
                                            }
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
                                            <span>{capitalizeFirstLetter(SurveyType.Popover)}</span>
                                            <span className="card-secondary mt-4">Questions</span>
                                            {survey.questions.map((q, idx) => (
                                                <span key={idx}>{q.question}</span>
                                            ))}
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
                                            {(survey.conditions || survey.targeting_flag) && (
                                                <div className="flex flex-col mt-6">
                                                    <span className="font-medium text-lg">Targeting</span>
                                                    {survey.conditions?.url && (
                                                        <>
                                                            <span className="card-secondary mt-4 mb-1 underline">
                                                                Url
                                                            </span>
                                                            <span>{survey.conditions.url}</span>
                                                            {(survey.conditions?.selector || survey.targeting_flag) && (
                                                                <LogicalRowDivider
                                                                    logicalOperator={FilterLogicalOperator.And}
                                                                />
                                                            )}
                                                        </>
                                                    )}
                                                    {survey.conditions?.selector && (
                                                        <>
                                                            <span className="card-secondary mt-4">Selector</span>
                                                            <span>{survey.conditions.selector}</span>
                                                        </>
                                                    )}
                                                    {survey.targeting_flag && (
                                                        <>
                                                            <span className="card-secondary mt-4 pb-1 underline">
                                                                Release conditions
                                                            </span>
                                                            {survey.targeting_flag.filters.groups.map(
                                                                (group, index) => (
                                                                    <>
                                                                        {index > 0 && (
                                                                            <div className="text-primary-alt font-semibold text-xs ml-2 py-1">
                                                                                OR
                                                                            </div>
                                                                        )}
                                                                        {group.properties.map((property, idx) => (
                                                                            <>
                                                                                <div
                                                                                    className="feature-flag-property-display"
                                                                                    key={idx}
                                                                                >
                                                                                    {idx === 0 ? (
                                                                                        <LemonButton
                                                                                            icon={
                                                                                                <IconSubArrowRight className="arrow-right" />
                                                                                            }
                                                                                            status="muted"
                                                                                            size="small"
                                                                                        />
                                                                                    ) : (
                                                                                        <LemonButton
                                                                                            icon={
                                                                                                <span className="text-sm">
                                                                                                    &
                                                                                                </span>
                                                                                            }
                                                                                            status="muted"
                                                                                            size="small"
                                                                                        />
                                                                                    )}
                                                                                    <span className="simple-tag tag-light-blue text-primary-alt">
                                                                                        {property.type === 'cohort'
                                                                                            ? 'Cohort'
                                                                                            : property.key}{' '}
                                                                                    </span>
                                                                                    {isPropertyFilterWithOperator(
                                                                                        property
                                                                                    ) ? (
                                                                                        <span>
                                                                                            {allOperatorsToHumanName(
                                                                                                property.operator
                                                                                            )}{' '}
                                                                                        </span>
                                                                                    ) : null}

                                                                                    {property.type === 'cohort' ? (
                                                                                        <a
                                                                                            href={urls.cohort(
                                                                                                property.value
                                                                                            )}
                                                                                            target="_blank"
                                                                                            rel="noopener"
                                                                                            className="simple-tag tag-light-blue text-primary-alt display-value"
                                                                                        >
                                                                                            {(property.value &&
                                                                                                cohortsById[
                                                                                                    property.value
                                                                                                ]?.name) ||
                                                                                                `ID ${property.value}`}
                                                                                        </a>
                                                                                    ) : (
                                                                                        [
                                                                                            ...(Array.isArray(
                                                                                                property.value
                                                                                            )
                                                                                                ? property.value
                                                                                                : [property.value]),
                                                                                        ].map((val, idx) => (
                                                                                            <span
                                                                                                key={idx}
                                                                                                className="simple-tag tag-light-blue text-primary-alt display-value"
                                                                                            >
                                                                                                {val}
                                                                                            </span>
                                                                                        ))
                                                                                    )}
                                                                                </div>
                                                                            </>
                                                                        ))}
                                                                    </>
                                                                )
                                                            )}
                                                        </>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                        <div className="w-full">
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
                                                                    <div className="flex gap-1 items-center">
                                                                        <LemonCheckbox checked={!!surveyPlugin} />{' '}
                                                                        {surveyPlugin ? (
                                                                            <span>Install survey app</span>
                                                                        ) : (
                                                                            <LemonButton onClick={installSurveyPlugin}>
                                                                                Install the survey app
                                                                            </LemonButton>
                                                                        )}{' '}
                                                                        {installingPlugin && <Spinner />}
                                                                    </div>
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
                                              <div className="flex flex-row gap-4">
                                                  {/* <div className="border rounded p-4">
                                              <span>Impressions</span>
                                              <h2>{surveyImpressionsCount}</h2>
                                          </div>
                                          <div className="border rounded p-4">
                                              <span>Started</span>
                                              <h2>{surveyStartedCount}</h2>
                                          </div>
                                          <div className="border rounded p-4">
                                              <span>Completed</span>
                                              <h2>{surveyCompletedCount}</h2>
                                          </div> */}
                                              </div>
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
            <SurveyLaunchSetupModal
                isOpen={setupModalIsOpen}
                closeModal={() => setSetupModalIsOpen(false)}
                launchSurvey={() => {
                    installSurveyPlugin()
                    launchSurvey()
                    setSetupModalIsOpen(false)
                }}
            />
        </div>
    )
}

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`

interface SurveyLaunchSetupModalProps {
    isOpen: boolean
    closeModal: () => void
    launchSurvey: () => void
}

function SurveyLaunchSetupModal({ isOpen, closeModal, launchSurvey }: SurveyLaunchSetupModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            width={600}
            title="Launch setup instructions"
            description="To launch this survey, you'll need to make sure you've enabled site apps in your PostHog instance by adding this option:"
            footer={
                <div className="flex gap-4">
                    <LemonButton type="primary" onClick={launchSurvey}>
                        Launch
                    </LemonButton>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                </div>
            }
        >
            <CodeSnippet language={Language.JavaScript} wrap>
                {OPT_IN_SNIPPET}
            </CodeSnippet>
            Launching this survey will install the surveys app for your project. You can then enable the app and save it
            to complete the setup.
        </LemonModal>
    )
}
