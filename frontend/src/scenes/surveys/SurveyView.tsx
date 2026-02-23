import './SurveyView.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconArchive, IconGraph, IconLlmAnalytics, IconThumbsDown, IconThumbsUp, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { organizationLogic } from 'scenes/organizationLogic'
import { DuplicateToProjectModal } from 'scenes/surveys/DuplicateToProjectModal'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { SurveyOverview } from 'scenes/surveys/SurveyOverview'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { SurveyResultDemo } from 'scenes/surveys/SurveyResultDemo'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'
import { SurveyViewRedesign } from 'scenes/surveys/SurveyViewRedesign'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { canDeleteSurvey, openArchiveSurveyDialog, openDeleteSurveyDialog } from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryContextColumn } from '~/queries/types'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { SurveyHeadline } from './SurveyHeadline'
import { getSurveyResponse, isThumbQuestion } from './utils'

const RESOURCE_TYPE = 'survey'

const getTraceIdFromRecord = (record: unknown): string | null => {
    if (!Array.isArray(record)) {
        return null
    }
    const event = record[0] as { properties?: { $ai_trace_id?: string } } | undefined
    return event?.properties?.$ai_trace_id ?? null
}

export const getThumbIcon = (value: unknown): JSX.Element | null => {
    if (value == '1') {
        return <IconThumbsUp className="text-brand-blue" />
    }
    if (value == '2') {
        return <IconThumbsDown className="text-warning" />
    }
    return null
}

export function SurveyView({ id }: { id: string }): JSX.Element {
    const isRedesignEnabled = useFeatureFlag('SURVEYS_REDESIGNED_VIEW')

    if (isRedesignEnabled) {
        return <SurveyViewRedesign />
    }

    return <SurveyViewLegacy id={id} />
}

function SurveyViewLegacy({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading } = useValues(surveyLogic)
    const { editingSurvey, updateSurvey, stopSurvey, resumeSurvey, archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { guidedEditorEnabled } = useValues(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')

    const surveyId = survey?.id && survey.id !== 'new' ? survey.id : null

    useFileSystemLogView({
        type: 'survey',
        ref: surveyId,
        enabled: Boolean(surveyId && !surveyLoading),
        deps: [surveyId, surveyLoading],
    })

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
                <SceneContent>
                    <ScenePanel>
                        <ScenePanelInfoSection>
                            <SceneFile dataAttrKey={RESOURCE_TYPE} />
                        </ScenePanelInfoSection>
                        <ScenePanelDivider />
                        <ScenePanelActionsSection>
                            <SceneDuplicate
                                dataAttrKey={RESOURCE_TYPE}
                                onClick={() => {
                                    // SurveyView is only rendered for existing surveys, so we can safely cast
                                    const existingSurvey = survey as Survey
                                    if (hasMultipleProjects) {
                                        setSurveyToDuplicate(existingSurvey)
                                    } else {
                                        duplicateSurvey(existingSurvey)
                                    }
                                }}
                            />
                        </ScenePanelActionsSection>
                        <ScenePanelDivider />
                        {!survey.archived && (
                            <ScenePanelActionsSection>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Survey}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={survey.user_access_level}
                                >
                                    <ButtonPrimitive
                                        menuItem
                                        data-attr={`${RESOURCE_TYPE}-archive`}
                                        onClick={() => openArchiveSurveyDialog(survey, archiveSurvey)}
                                    >
                                        <IconArchive />
                                        Archive
                                    </ButtonPrimitive>
                                </AccessControlAction>
                            </ScenePanelActionsSection>
                        )}
                        {canDeleteSurvey(survey) && (
                            <ScenePanelActionsSection>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Survey}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={survey.user_access_level}
                                >
                                    <ButtonPrimitive
                                        menuItem
                                        variant="danger"
                                        data-attr={`${RESOURCE_TYPE}-delete`}
                                        onClick={() => openDeleteSurveyDialog(survey, () => deleteSurvey(id))}
                                    >
                                        <IconTrash />
                                        Delete permanently
                                    </ButtonPrimitive>
                                </AccessControlAction>
                            </ScenePanelActionsSection>
                        )}
                    </ScenePanel>

                    <SceneTitleSection
                        name={survey.name}
                        description={survey.description}
                        resourceType={{
                            type: 'survey',
                        }}
                        canEdit={userHasAccess(
                            AccessControlResourceType.Survey,
                            AccessControlLevel.Editor,
                            survey.user_access_level
                        )}
                        saveOnBlur
                        onNameChange={(name) => updateSurvey({ id, name })}
                        onDescriptionChange={(description) => updateSurvey({ id, description })}
                        renameDebounceMs={0}
                        isLoading={surveyLoading}
                        actions={
                            <>
                                <SurveyFeedbackButton />
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Survey}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={survey.user_access_level}
                                >
                                    <LemonButton
                                        data-attr="edit-survey"
                                        onClick={
                                            guidedEditorEnabled && survey.type === SurveyType.Popover
                                                ? undefined
                                                : () => editingSurvey(true)
                                        }
                                        to={
                                            guidedEditorEnabled && survey.type === SurveyType.Popover
                                                ? urls.surveyWizard(id)
                                                : undefined
                                        }
                                        type="secondary"
                                        size="small"
                                    >
                                        Edit
                                    </LemonButton>
                                </AccessControlAction>
                                {!survey.start_date ? (
                                    <LaunchSurveyButton />
                                ) : survey.end_date && !survey.archived ? (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Survey}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={survey.user_access_level}
                                    >
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Resume this survey?',
                                                    content: (
                                                        <div className="text-sm text-secondary">
                                                            Once resumed, the survey will be visible to your users
                                                            again.
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
                                    </AccessControlAction>
                                ) : (
                                    !survey.archived && (
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.Survey}
                                            minAccessLevel={AccessControlLevel.Editor}
                                            userAccessLevel={survey.user_access_level}
                                        >
                                            <LemonButton
                                                data-attr="stop-survey"
                                                type="secondary"
                                                status="danger"
                                                size="small"
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
                                        </AccessControlAction>
                                    )
                                )}
                            </>
                        }
                    />
                    <LemonTabs
                        activeKey={tabKey}
                        onChange={(key) => setTabKey(key)}
                        sceneInset
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
                                : {
                                      content: <SurveyResultDemo />,
                                      key: 'results',
                                      label: 'Results (Demo)',
                                  },
                            {
                                content: <SurveyOverview onTabChange={setTabKey} />,
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
                                            type="destination"
                                            subTemplateIds={['survey-response']}
                                            forceFilterGroups={[
                                                {
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
                                                },
                                            ]}
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
                    <DuplicateToProjectModal />
                </SceneContent>
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

export function SurveyResult({ disableEventsTable }: { disableEventsTable?: boolean }): JSX.Element {
    const {
        survey,
        dataTableQuery,
        surveyLoading,
        surveyAsInsightURL,
        isAnyResultsLoading,
        processedSurveyStats,
        archivedResponseUuids,
        isSurveyHeadlineEnabled,
    } = useValues(surveyLogic)

    /**
     * custom column renderer that does:
     * - shows LLM trace button on the first question, if the event has an $ai_trace_id
     * - shows thumbs up/down icons instead of the raw '1'/'2' data for thumb questions
     */
    const surveyColumnRenderers = useMemo(() => {
        const columns: Record<string, QueryContextColumn> = {}

        survey.questions.forEach((question, index) => {
            const isThumb = isThumbQuestion(question)
            const isFirstQuestion = index === 0

            if (!isThumb && !isFirstQuestion) {
                return
            }

            const columnName = getSurveyResponse(question, index)
            columns[columnName] = {
                render: ({ value, record }) => {
                    const traceId = isFirstQuestion ? getTraceIdFromRecord(record) : null

                    return (
                        <span className="flex items-center gap-2">
                            {/* show LLM trace button on the first question if we have $ai_trace_id */}
                            {traceId && (
                                <Tooltip title="View LLM trace">
                                    <LemonButton
                                        size="xsmall"
                                        icon={
                                            <IconLlmAnalytics className="text-[var(--color-product-llm-analytics-light)]" />
                                        }
                                        to={urls.llmAnalyticsTrace(traceId)}
                                    />
                                </Tooltip>
                            )}

                            {/* replace '1' and '2' with thumb icon+text if it's a thumb question */}
                            {isThumb ? (
                                <span className="flex items-center gap-1">
                                    {getThumbIcon(value)}
                                    Thumbs {value == '1' ? 'up' : 'down'}
                                </span>
                            ) : (
                                String(value)
                            )}
                        </span>
                    )
                },
            }
        })

        return columns
    }, [survey.questions])

    const atLeastOneResponse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count
    return (
        <div className="deprecated-space-y-4">
            {isSurveyHeadlineEnabled && <SurveyHeadline />}
            <SurveyResponseFilters />
            <SurveyStatsSummary />
            {isAnyResultsLoading || atLeastOneResponse ? (
                <>
                    <SurveyResponsesByQuestionV2 />
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
                                <Query
                                    query={dataTableQuery}
                                    context={{
                                        columns: surveyColumnRenderers,
                                        rowProps: (record: unknown) => {
                                            // "mute" archived records
                                            if (typeof record !== 'object' || !record || !('result' in record)) {
                                                return {}
                                            }
                                            const result = record.result
                                            if (!Array.isArray(result)) {
                                                return {}
                                            }
                                            return {
                                                className: archivedResponseUuids.has(result[0].uuid)
                                                    ? 'opacity-50'
                                                    : undefined,
                                            }
                                        },
                                    }}
                                />
                            </div>
                        ))}
                </>
            ) : (
                <SurveyNoResponsesBanner type="survey" />
            )}
        </div>
    )
}
