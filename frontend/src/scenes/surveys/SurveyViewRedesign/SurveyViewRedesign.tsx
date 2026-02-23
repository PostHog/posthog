import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArchive, IconCode, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { DuplicateToProjectModal } from 'scenes/surveys/DuplicateToProjectModal'
import { SurveyHeadline } from 'scenes/surveys/SurveyHeadline'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { SurveySQLHelper } from 'scenes/surveys/SurveySQLHelper'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { canDeleteSurvey, openArchiveSurveyDialog, openDeleteSurveyDialog } from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyStatus, surveysLogic } from 'scenes/surveys/surveysLogic'
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
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    ProgressStatus,
    Survey,
    SurveyEventName,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { SurveyDraftContent } from './SurveyDraftContent'
import { SurveyResultsFiltersBar } from './SurveyFilters'
import { SurveyDetailsPanel, SurveyExportPanel, SurveyNotificationsPanel } from './SurveySidebar'

const RESOURCE_TYPE = 'survey'

export function SurveyViewRedesign(): JSX.Element {
    const { survey, surveyLoading } = useValues(surveyLogic)
    const { editingSurvey, updateSurvey, archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { guidedEditorEnabled } = useValues(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1
    const [tabKey, setTabKey] = useState('summary')
    const [panelTabKey, setPanelTabKey] = useState('details')
    const [sqlHelperOpen, setSqlHelperOpen] = useState(false)
    const status = getSurveyStatus(survey)
    const isDraft = status === ProgressStatus.Draft

    if (surveyLoading) {
        return <LemonSkeleton />
    }

    return (
        <SceneContent className="gap-y-4 flex-1 min-h-full">
            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneFile dataAttrKey={RESOURCE_TYPE} />
                </ScenePanelInfoSection>
                <ScenePanelDivider />
                <ScenePanelActionsSection>
                    <SceneDuplicate
                        dataAttrKey={RESOURCE_TYPE}
                        onClick={() => {
                            const existingSurvey = survey as Survey
                            if (hasMultipleProjects) {
                                setSurveyToDuplicate(existingSurvey)
                            } else {
                                duplicateSurvey(existingSurvey)
                            }
                        }}
                    />
                    {!isDraft && (
                        <ButtonPrimitive menuItem onClick={() => setSqlHelperOpen(true)}>
                            <IconCode />
                            SQL query
                        </ButtonPrimitive>
                    )}
                    {!survey.archived && (
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
                    )}
                    {canDeleteSurvey(survey) && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Survey}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={survey.user_access_level}
                        >
                            <ButtonPrimitive
                                menuItem
                                variant="danger"
                                data-attr={`${RESOURCE_TYPE}-delete`}
                                onClick={() => openDeleteSurveyDialog(survey, () => deleteSurvey(survey.id))}
                            >
                                <IconTrash />
                                Delete permanently
                            </ButtonPrimitive>
                        </AccessControlAction>
                    )}
                </ScenePanelActionsSection>
                <ScenePanelDivider />

                {/* Survey-specific panels as sub-tabs */}
                <LemonTabs
                    size="small"
                    activeKey={panelTabKey}
                    onChange={(key) => setPanelTabKey(key)}
                    tabs={[
                        {
                            key: 'details',
                            label: 'Details',
                            content: <SurveyDetailsPanel />,
                        },
                        {
                            key: 'notifications',
                            label: 'Notifications',
                            content: <SurveyNotificationsPanel />,
                        },
                        ...(!isDraft
                            ? [
                                  {
                                      key: 'export',
                                      label: 'Export',
                                      content: <SurveyExportPanel />,
                                  },
                              ]
                            : []),
                    ]}
                />
            </ScenePanel>

            <SceneTitleSection
                name={survey.name}
                description={survey.description}
                resourceType={{ type: 'survey' }}
                canEdit={userHasAccess(
                    AccessControlResourceType.Survey,
                    AccessControlLevel.Editor,
                    survey.user_access_level
                )}
                saveOnBlur
                onNameChange={(name) => updateSurvey({ id: survey.id, name })}
                onDescriptionChange={(description) => updateSurvey({ id: survey.id, description })}
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
                                        ? urls.surveyWizard(survey.id)
                                        : undefined
                                }
                                type="secondary"
                                size="small"
                            >
                                Edit
                            </LemonButton>
                        </AccessControlAction>
                        <SurveyStatusAction />
                    </>
                }
            />

            {/* Main content */}
            <div className="-m-4 flex-1 min-h-0">
                <LemonTabs
                    activeKey={tabKey}
                    onChange={(key) => setTabKey(key)}
                    barClassName="pl-4 [&::before]:!bg-transparent border-b"
                    tabs={[
                        {
                            key: 'summary',
                            label: 'Summary',
                            content: isDraft ? (
                                <SurveyDraftContent />
                            ) : (
                                <SurveySummaryContent onViewResponses={() => setTabKey('responses')} />
                            ),
                        },
                        ...(!isDraft
                            ? [
                                  {
                                      key: 'responses',
                                      label: 'Responses',
                                      content: <SurveyResponsesContent />,
                                  },
                              ]
                            : []),
                        {
                            key: 'history',
                            label: 'History',
                            content: (
                                <div className="px-4 pb-4 max-w-4xl mx-auto">
                                    <ActivityLog scope={ActivityScope.SURVEY} id={survey.id} />
                                </div>
                            ),
                        },
                    ]}
                />
            </div>

            <DuplicateToProjectModal />
            <SurveySQLHelper isOpen={sqlHelperOpen} onClose={() => setSqlHelperOpen(false)} />
        </SceneContent>
    )
}

function SurveyStatusAction(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { stopSurvey, resumeSurvey } = useActions(surveyLogic)
    const status = getSurveyStatus(survey)

    if (status === ProgressStatus.Draft) {
        return <LaunchSurveyButton />
    }

    if (survey.archived) {
        return null
    }

    if (status === ProgressStatus.Complete) {
        return (
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
            </AccessControlAction>
        )
    }

    return (
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
}

function SurveySummaryContent({ onViewResponses }: { onViewResponses: () => void }): JSX.Element {
    const { survey, isAnyResultsLoading, processedSurveyStats, isSurveyHeadlineEnabled } = useValues(surveyLogic)

    const atLeastOneResponse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count

    if (!isAnyResultsLoading && !atLeastOneResponse) {
        return (
            <div className="space-y-4 px-4 pb-4">
                <SurveyResultsFiltersBar />
                <SurveyStatsSummary />
                <SurveyNoResponsesBanner type="survey" />
            </div>
        )
    }

    return (
        <div className="space-y-4 px-4 pb-4">
            <SurveyResultsFiltersBar />
            <SurveyStatsSummary />
            {isSurveyHeadlineEnabled && <SurveyHeadline />}

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
            <LemonButton
                type="tertiary"
                data-attr="survey-results-view-responses"
                onClick={onViewResponses}
                size="small"
            >
                Looking for all responses?
            </LemonButton>
        </div>
    )
}

function SurveyResponsesContent(): JSX.Element {
    const { dataTableQuery, surveyLoading, archivedResponseUuids } = useValues(surveyLogic)

    return (
        <div className="px-4 pb-4 space-y-4">
            <SurveyResultsFiltersBar />
            {surveyLoading ? (
                <LemonSkeleton />
            ) : (
                <div className="survey-table-results">
                    <Query
                        query={dataTableQuery}
                        context={{
                            rowProps: (record: unknown) => {
                                if (typeof record !== 'object' || !record || !('result' in record)) {
                                    return {}
                                }
                                const result = record.result
                                if (!Array.isArray(result)) {
                                    return {}
                                }
                                return {
                                    className: archivedResponseUuids.has(result[0].uuid) ? 'opacity-50' : undefined,
                                }
                            },
                        }}
                    />
                </div>
            )}
        </div>
    )
}
