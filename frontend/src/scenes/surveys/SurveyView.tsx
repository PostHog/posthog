import './SurveyView.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGraph, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
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
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveyStartSchedulePicker } from 'scenes/surveys/components/SurveyStartSchedulePicker'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { buildSurveyResumeUpdatePayload } from 'scenes/surveys/surveyScheduling'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { ProductIntentContext } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
} from '~/types'

import { SurveyHeadline } from './SurveyHeadline'
import { SurveysDisabledBanner } from './SurveySettings'

const RESOURCE_TYPE = 'survey'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading } = useValues(surveyLogic)
    const { editingSurvey, updateSurvey, stopSurvey, duplicateSurvey, setIsDuplicateToProjectModalOpen } =
        useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')

    const [isResumeDialogOpen, setIsResumeDialogOpen] = useState(false)
    const [resumeScheduledStartTime, setResumeScheduledStartTime] = useState<string | undefined>(undefined)

    const [isStopDialogOpen, setIsStopDialogOpen] = useState(false)
    const [stopScheduledEndTime, setStopScheduledEndTime] = useState<string | undefined>(undefined)

    const closeResumeDialog = (): void => {
        setIsResumeDialogOpen(false)
    }

    const closeStopDialog = (): void => {
        setIsStopDialogOpen(false)
    }

    const resumeSurveyWithSchedule = async (): Promise<void> => {
        try {
            await updateSurvey({
                ...buildSurveyResumeUpdatePayload(resumeScheduledStartTime),
                intentContext: ProductIntentContext.SURVEY_RESUMED,
            })
            closeResumeDialog()
        } catch {
            lemonToast.error('Failed to resume survey. Please try again.')
        }
    }

    const stopSurveyWithSchedule = async (): Promise<void> => {
        try {
            if (!stopScheduledEndTime) {
                await stopSurvey()
            } else {
                await updateSurvey({
                    scheduled_end_datetime: stopScheduledEndTime,
                })
            }
            closeStopDialog()
        } catch {
            lemonToast.error('Failed to stop survey. Please try again.')
        }
    }

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
                                    if (hasMultipleProjects) {
                                        setIsDuplicateToProjectModalOpen(true)
                                    } else {
                                        duplicateSurvey()
                                    }
                                }}
                            />
                        </ScenePanelActionsSection>
                        <ScenePanelDivider />
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
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete this survey?',
                                            content: (
                                                <div className="text-sm text-secondary">
                                                    This action cannot be undone. All survey data will be permanently
                                                    removed.
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
                                    <IconTrash />
                                    Delete survey
                                </ButtonPrimitive>
                            </AccessControlAction>
                        </ScenePanelActionsSection>
                    </ScenePanel>

                    <SurveysDisabledBanner />
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
                                        onClick={() => editingSurvey(true)}
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
                                                setResumeScheduledStartTime(
                                                    survey.scheduled_start_datetime
                                                        ? survey.scheduled_start_datetime
                                                        : undefined
                                                )
                                                setIsResumeDialogOpen(true)
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
                                                    setStopScheduledEndTime(
                                                        survey.scheduled_end_datetime
                                                            ? survey.scheduled_end_datetime
                                                            : undefined
                                                    )
                                                    setIsStopDialogOpen(true)
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

                    {isResumeDialogOpen && (
                        <LemonDialog
                            title="Resume this survey?"
                            onClose={closeResumeDialog}
                            onAfterClose={closeResumeDialog}
                            shouldAwaitSubmit
                            content={
                                <div>
                                    <div className="text-sm text-secondary mb-4">
                                        Make this survey visible to your users again:
                                    </div>
                                    <SurveyStartSchedulePicker
                                        value={resumeScheduledStartTime}
                                        onChange={setResumeScheduledStartTime}
                                        manualLabel="Immediately"
                                        datetimeLabel="In the future"
                                        defaultDatetimeValue={() => new Date(Date.now() + 60 * 60 * 1000).toISOString()}
                                    />
                                </div>
                            }
                            primaryButton={{
                                children: resumeScheduledStartTime ? 'Schedule resume' : 'Resume',
                                type: 'primary',
                                onClick: resumeSurveyWithSchedule,
                                preventClosing: true,
                                size: 'small',
                            }}
                            secondaryButton={{
                                children: 'Cancel',
                                type: 'tertiary',
                                size: 'small',
                            }}
                        />
                    )}

                    {isStopDialogOpen && (
                        <LemonDialog
                            title="Stop this survey?"
                            onClose={closeStopDialog}
                            onAfterClose={closeStopDialog}
                            shouldAwaitSubmit
                            content={
                                <div>
                                    <div className="text-sm text-secondary mb-4">
                                        Stop displaying this survey to users:
                                    </div>
                                    <SurveyStartSchedulePicker
                                        value={stopScheduledEndTime}
                                        onChange={setStopScheduledEndTime}
                                        manualLabel="Immediately"
                                        datetimeLabel="In the future"
                                        defaultDatetimeValue={() => new Date(Date.now() + 60 * 60 * 1000).toISOString()}
                                    />
                                </div>
                            }
                            primaryButton={{
                                children: stopScheduledEndTime ? 'Schedule stop' : 'Stop',
                                type: 'primary',
                                status: 'danger',
                                onClick: stopSurveyWithSchedule,
                                preventClosing: true,
                                size: 'small',
                            }}
                            secondaryButton={{
                                children: 'Cancel',
                                type: 'tertiary',
                                size: 'small',
                            }}
                        />
                    )}
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
                    {hasMultipleProjects && <DuplicateToProjectModal />}
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
        dataTableQuery,
        surveyLoading,
        surveyAsInsightURL,
        isAnyResultsLoading,
        processedSurveyStats,
        archivedResponseUuids,
        isSurveyHeadlineEnabled,
    } = useValues(surveyLogic)

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
