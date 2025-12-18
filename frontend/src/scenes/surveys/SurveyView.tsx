import './SurveyView.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGraph, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { dayjs } from 'lib/dayjs'
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
import { SurveyResumeDialog, SurveyStopDialog } from 'scenes/surveys/components/SurveyLifecycleDialogs'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { buildSurveyResumeUpdatePayload, buildSurveyStopUpdatePayload } from 'scenes/surveys/surveyScheduling'
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
    const { editingSurvey, updateSurvey, duplicateSurvey, setIsDuplicateToProjectModalOpen } = useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')
    const [isResumeDialogOpen, setIsResumeDialogOpen] = useState(false)
    const [isStopDialogOpen, setIsStopDialogOpen] = useState(false)

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

                    <SurveyResumeDialog
                        isOpen={isResumeDialogOpen}
                        onClose={() => setIsResumeDialogOpen(false)}
                        initialScheduledStartTime={survey.scheduled_start_datetime || undefined}
                        description="Make this survey visible to your users again:"
                        defaultDatetimeValue={() => dayjs().toISOString()}
                        onSubmit={async (scheduledStartTime) => {
                            await updateSurvey({
                                ...buildSurveyResumeUpdatePayload(scheduledStartTime),
                                intentContext: ProductIntentContext.SURVEY_RESUMED,
                            })
                        }}
                    />

                    <SurveyStopDialog
                        isOpen={isStopDialogOpen}
                        onClose={() => setIsStopDialogOpen(false)}
                        initialScheduledEndTime={survey.scheduled_end_datetime || undefined}
                        description="Stop displaying this survey to users:"
                        defaultDatetimeValue={() => dayjs().toISOString()}
                        onSubmit={async (scheduledEndTime) => {
                            await updateSurvey({
                                ...buildSurveyStopUpdatePayload(scheduledEndTime, dayjs().toISOString()),
                                ...(scheduledEndTime ? {} : { intentContext: ProductIntentContext.SURVEY_COMPLETED }),
                            })
                        }}
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
