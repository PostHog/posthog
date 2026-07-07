import './SurveyView.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconArchive, IconCopy, IconGraph, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveyNotificationModal } from 'scenes/surveys/components/SurveyNotificationModal'
import { SurveyNotifications } from 'scenes/surveys/components/SurveyNotifications'
import { SurveyNotificationsCallout } from 'scenes/surveys/components/SurveyNotificationsCallout'
import { DuplicateToProjectModal } from 'scenes/surveys/DuplicateToProjectModal'
import {
    canDeleteSurvey,
    openArchiveSurveyDialog,
    openDeleteSurveyDialog,
    openResumeSurveyDialog,
} from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { SurveyOverview } from 'scenes/surveys/SurveyOverview'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { SurveyResultDemo } from 'scenes/surveys/SurveyResultDemo'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'
import { SurveyViewRedesign } from 'scenes/surveys/SurveyViewRedesign'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { Query } from '~/queries/Query/Query'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    Survey,
    SurveyEventName,
    SurveyQuestionType,
} from '~/types'

import { SurveyResultsRefreshStatus } from './components/SurveyResultsRefreshStatus'
import { NEW_SURVEY } from './constants'
import { useSurveyResponseColumns } from './hooks/useSurveyResponseColumns'
import { SurveyHeadline } from './SurveyHeadline'
import { SurveySceneMenuBar } from './SurveySceneMenuBar'
import { canUseSurveyWizard } from './utils'

const RESOURCE_TYPE = 'survey'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const isRedesignEnabled = useFeatureFlag('SURVEYS_REDESIGNED_VIEW')

    return (
        <>
            {isRedesignEnabled ? <SurveyViewRedesign /> : <SurveyViewLegacy id={id} />}
            <SurveyNotificationModal surveyId={id} />
        </>
    )
}

function SurveyViewLegacy({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, surveyNotifications } = useValues(surveyLogic)
    const { preferredEditor } = useValues(surveysLogic)
    const { editingSurvey, updateSurvey, stopSurvey, resumeSurvey, archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { push } = useActions(router)
    const isInitialSurveyLoad = surveyLoading && survey.id === NEW_SURVEY.id

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')

    const surveyId = survey?.id && survey.id !== 'new' ? survey.id : null

    useEffect(() => {
        if (survey.start_date) {
            setTabKey('results')
        } else {
            setTabKey('overview')
        }
    }, [survey.start_date])

    return (
        <div>
            {isInitialSurveyLoad ? (
                <LemonSkeleton />
            ) : (
                <SceneContent>
                    <SurveySceneMenuBar id={id} />
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
                            {canCopyToProject && surveyId && (
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() => push(urls.resourceTransfer('Survey', surveyId))}
                                    data-attr="survey-copy-to-project"
                                    tooltip="Copy this survey to another project"
                                >
                                    <IconCopy />
                                    Copy to another project
                                </ButtonPrimitive>
                            )}
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

                    {survey.archived && (
                        <LemonBanner type="warning" className="mb-4">
                            This survey is archived and is no longer collecting responses.
                        </LemonBanner>
                    )}
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
                                            canUseSurveyWizard(survey) && preferredEditor === 'guided'
                                                ? undefined
                                                : () => editingSurvey(true)
                                        }
                                        to={
                                            canUseSurveyWizard(survey) && preferredEditor === 'guided'
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
                                            onClick={() => openResumeSurveyDialog(survey, () => resumeSurvey())}
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
                                label: (
                                    <span className="flex items-center gap-1.5">
                                        Notifications
                                        {surveyNotifications.length > 0 && (
                                            <LemonTag type="completion" size="small">
                                                {surveyNotifications.length}
                                            </LemonTag>
                                        )}
                                    </span>
                                ),
                                content: (
                                    <SurveyNotifications
                                        surveyId={id}
                                        description="Get notified whenever a survey result is submitted."
                                    />
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
        resultsRequeryInProgress,
        processedSurveyStats,
        archivedResponseUuids,
        isSurveyHeadlineEnabled,
        hasActiveFilters,
        hasActiveAnswerFilters,
        hasActiveDateRange,
        propertyFilters,
    } = useValues(surveyLogic)
    const { clearFilters } = useActions(surveyLogic)
    const isInitialSurveyLoad = surveyLoading && survey.id === NEW_SURVEY.id
    const surveyColumnRenderers = useSurveyResponseColumns()

    const atLeastOneResponse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count
    const isRefreshingResults = resultsRequeryInProgress || isAnyResultsLoading
    return (
        <div className="deprecated-space-y-4">
            {isSurveyHeadlineEnabled && <SurveyHeadline />}
            <SurveyResponseFilters />
            <SurveyNotificationsCallout surveyId={survey.id} />
            {isRefreshingResults || atLeastOneResponse ? (
                <>
                    <SurveyResultsRefreshStatus visible={isRefreshingResults} />
                    <div
                        aria-busy={isRefreshingResults}
                        className={
                            isRefreshingResults
                                ? 'opacity-75 transition-opacity duration-200 ease-out'
                                : 'opacity-100 transition-opacity duration-200 ease-out'
                        }
                    >
                        <SurveyStatsSummary />
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
                            (isInitialSurveyLoad ? (
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
                                                    className:
                                                        result[0]?.uuid && archivedResponseUuids.has(result[0].uuid)
                                                            ? 'opacity-50'
                                                            : undefined,
                                                }
                                            },
                                        }}
                                    />
                                </div>
                            ))}
                    </div>
                </>
            ) : (
                <>
                    <SurveyStatsSummary />
                    <SurveyNoResponsesBanner
                        type="survey"
                        isFiltered={hasActiveFilters}
                        onClearFilters={hasActiveFilters ? clearFilters : undefined}
                        activeFilterTypes={{
                            dateRange: hasActiveDateRange,
                            answerFilters: hasActiveAnswerFilters,
                            propertyFilters: propertyFilters.length > 0,
                        }}
                    />
                </>
            )}
        </div>
    )
}
