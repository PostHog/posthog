import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconArchive, IconCode, IconCopy, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import { SurveyNotifications } from 'scenes/surveys/components/SurveyNotifications'
import { SurveyNotificationsCallout } from 'scenes/surveys/components/SurveyNotificationsCallout'
import { DuplicateToProjectModal } from 'scenes/surveys/DuplicateToProjectModal'
import { useSurveyResponseColumns } from 'scenes/surveys/hooks/useSurveyResponseColumns'
import {
    canDeleteSurvey,
    openArchiveSurveyDialog,
    openDeleteSurveyDialog,
    openResumeSurveyDialog,
} from 'scenes/surveys/surveyDialogs'
import { SurveyHeadline } from 'scenes/surveys/SurveyHeadline'
import { SurveyTab, surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { getSurveyStatus, isSurveyDraft, surveysLogic } from 'scenes/surveys/surveysLogic'
import { SurveySQLHelper } from 'scenes/surveys/SurveySQLHelper'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'
import { canUseSurveyWizard } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { Query } from '~/queries/Query/Query'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    ProgressStatus,
    SidePanelTab,
    Survey,
    SurveyEventName,
    SurveyQuestionType,
} from '~/types'

import { SurveyResultsRefreshStatus } from '../components/SurveyResultsRefreshStatus'
import { NEW_SURVEY } from '../constants'
import { SurveyDraftContent } from './SurveyDraftContent'
import { SurveyResultsFiltersBar } from './SurveyFilters'
import { SurveyResponseExpandedRow } from './SurveyResponseExpandedRow'
import { SurveyDetailsPanel, SurveyExportPanel } from './SurveySidebar'

const RESOURCE_TYPE = 'survey'

export function SurveyViewRedesign(): JSX.Element {
    const { survey, surveyLoading, activeTab, surveyNotifications } = useValues(surveyLogic)
    const { preferredEditor } = useValues(surveysLogic)
    const { editingSurvey, updateSurvey, archiveSurvey, setActiveTab } = useActions(surveyLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { sidePanelOpen, selectedTab: selectedSidePanelTab } = useValues(sidePanelStateLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { push } = useActions(router)
    const { location, searchParams, hashParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const isInitialSurveyLoad = surveyLoading && survey.id === NEW_SURVEY.id

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1
    const surveyIdForTransfer = survey?.id && survey.id !== 'new' ? survey.id : null
    const isDraft = isSurveyDraft(survey)
    const [panelTabKey, setPanelTabKey] = useState('details')
    const [sqlHelperOpen, setSqlHelperOpen] = useState(false)
    const autoOpenedDraftPanelForSurveyIdRef = useRef<string | null>(null)
    const isRemovingSidePanel = useFeatureFlag('UX_REMOVE_SIDEPANEL')
    const panelTabSearchParam = 'survey_panel_tab'

    const panelTabs = useMemo(
        () => [
            {
                key: 'details',
                label: 'Details',
                content: <SurveyDetailsPanel />,
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
        ],
        [isDraft]
    )
    const validPanelTabKeys = useMemo(() => panelTabs.map((tab) => tab.key), [panelTabs])

    const setPanelTab = useCallback(
        (key: string, syncToUrl: boolean = true): void => {
            setPanelTabKey(key)
            if (!syncToUrl) {
                return
            }
            router.actions.replace(location.pathname, { ...searchParams, [panelTabSearchParam]: key }, hashParams)
        },
        [hashParams, location.pathname, searchParams]
    )

    // Prevent duplicate right-side panels in UX_REMOVE_SIDEPANEL mode:
    // this scene should render details only in the side panel's Info tab.
    useEffect(() => {
        if (isRemovingSidePanel) {
            setScenePanelOpen(false)
        }
    }, [isRemovingSidePanel, setScenePanelOpen])

    useEffect(() => {
        const tabFromUrl = searchParams[panelTabSearchParam]
        if (typeof tabFromUrl !== 'string') {
            return
        }
        if (validPanelTabKeys.includes(tabFromUrl) && panelTabKey !== tabFromUrl) {
            setPanelTab(tabFromUrl, false)
            return
        }
        if (!validPanelTabKeys.includes(tabFromUrl)) {
            const { [panelTabSearchParam]: _invalid, ...nextSearchParams } = searchParams
            router.actions.replace(location.pathname, nextSearchParams, hashParams)
        }
    }, [hashParams, location.pathname, panelTabKey, searchParams, setPanelTab, validPanelTabKeys])

    const openDraftDetails = useCallback((): void => {
        setPanelTab('details')
        if (isRemovingSidePanel) {
            openSidePanel(SidePanelTab.Info)
            setScenePanelOpen(false)
        } else {
            setScenePanelOpen(true)
        }
    }, [isRemovingSidePanel, openSidePanel, setPanelTab, setScenePanelOpen])

    useEffect(() => {
        if (!isDraft) {
            const autoOpenedSurveyId = autoOpenedDraftPanelForSurveyIdRef.current
            if (autoOpenedSurveyId) {
                if (isRemovingSidePanel) {
                    if (sidePanelOpen && selectedSidePanelTab === SidePanelTab.Info) {
                        closeSidePanel(SidePanelTab.Info)
                    }
                    setScenePanelOpen(false)
                } else {
                    setScenePanelOpen(false)
                }
            }
            autoOpenedDraftPanelForSurveyIdRef.current = null
            return
        }

        const surveyId = survey?.id ? String(survey.id) : null
        if (!surveyId || autoOpenedDraftPanelForSurveyIdRef.current === surveyId) {
            return
        }

        autoOpenedDraftPanelForSurveyIdRef.current = surveyId

        const tabFromUrl = searchParams[panelTabSearchParam]
        const draftTab =
            typeof tabFromUrl === 'string' && validPanelTabKeys.includes(tabFromUrl) ? tabFromUrl : 'details'
        setPanelTab(draftTab, false)

        if (isRemovingSidePanel) {
            openSidePanel(SidePanelTab.Info)
            setScenePanelOpen(false)
        } else {
            setScenePanelOpen(true)
        }
    }, [
        isDraft,
        isRemovingSidePanel,
        closeSidePanel,
        openSidePanel,
        selectedSidePanelTab,
        searchParams,
        setPanelTab,
        setScenePanelOpen,
        sidePanelOpen,
        survey?.id,
        validPanelTabKeys,
    ])

    if (isInitialSurveyLoad) {
        return <LemonSkeleton />
    }

    return (
        <SceneContent className="gap-y-4 flex-1 min-h-full">
            {sceneMenuBarEnabled && (
                <SceneMenuBar>
                    <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                        <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                        {canCopyToProject && surveyIdForTransfer && (
                            <SceneMenuBarItem
                                onClick={() => push(urls.resourceTransfer('Survey', surveyIdForTransfer))}
                                data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                            >
                                <IconCopy />
                                Copy to another project
                            </SceneMenuBarItem>
                        )}
                        {(!survey.archived || canDeleteSurvey(survey)) && <SceneMenuBarSeparator />}
                        {!survey.archived && (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Survey}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={survey.user_access_level}
                            >
                                {({ disabledReason }) => (
                                    <SceneMenuBarItem
                                        variant="destructive"
                                        opensFloatingUi
                                        disabled={!!disabledReason}
                                        onClick={() => openArchiveSurveyDialog(survey, archiveSurvey)}
                                        data-attr={`${RESOURCE_TYPE}-menubar-archive`}
                                    >
                                        <IconArchive />
                                        Archive
                                    </SceneMenuBarItem>
                                )}
                            </AccessControlAction>
                        )}
                        {canDeleteSurvey(survey) && (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Survey}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={survey.user_access_level}
                            >
                                {({ disabledReason }) => (
                                    <SceneMenuBarItem
                                        variant="destructive"
                                        opensFloatingUi
                                        disabled={!!disabledReason}
                                        onClick={() => openDeleteSurveyDialog(survey, () => deleteSurvey(survey.id))}
                                        data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                                    >
                                        <IconTrash />
                                        Delete permanently
                                    </SceneMenuBarItem>
                                )}
                            </AccessControlAction>
                        )}
                    </SceneMenuBarMenu>
                    <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                        <SceneMenuBarItem
                            onClick={() => {
                                const existingSurvey = survey as Survey
                                if (hasMultipleProjects) {
                                    setSurveyToDuplicate(existingSurvey)
                                } else {
                                    duplicateSurvey(existingSurvey)
                                }
                            }}
                            data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                        >
                            <IconCopy />
                            Duplicate
                        </SceneMenuBarItem>
                        {!isDraft && (
                            <SceneMenuBarItem
                                opensFloatingUi
                                onClick={() => setSqlHelperOpen(true)}
                                data-attr={`${RESOURCE_TYPE}-menubar-sql-query`}
                            >
                                <IconCode />
                                SQL query
                            </SceneMenuBarItem>
                        )}
                    </SceneMenuBarMenu>
                </SceneMenuBar>
            )}
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
                    {canCopyToProject && surveyIdForTransfer && (
                        <ButtonPrimitive
                            menuItem
                            onClick={() => push(urls.resourceTransfer('Survey', surveyIdForTransfer))}
                            data-attr="survey-copy-to-project"
                            tooltip="Copy this survey to another project"
                        >
                            <IconCopy />
                            Copy to another project
                        </ButtonPrimitive>
                    )}
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
                <LemonTabs size="small" activeKey={panelTabKey} onChange={(key) => setPanelTab(key)} tabs={panelTabs} />
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
                                    canUseSurveyWizard(survey) && preferredEditor === 'guided'
                                        ? undefined
                                        : () => editingSurvey(true)
                                }
                                to={
                                    canUseSurveyWizard(survey) && preferredEditor === 'guided'
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
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as SurveyTab)}
                    barClassName="pl-4 [&::before]:!bg-transparent border-b"
                    tabs={[
                        {
                            key: 'summary',
                            label: 'Summary',
                            content: isDraft ? (
                                <SurveyDraftContent onSeeSurveyDetails={openDraftDetails} />
                            ) : (
                                <SurveySummaryContent onViewResponses={() => setActiveTab(SurveyTab.RESPONSES)} />
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
                            key: SurveyTab.NOTIFICATIONS,
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
                            content: <SurveyNotificationsContent />,
                        },
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

function SurveyNotificationsContent(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    return (
        <div className="px-4 pb-4">
            <div className="mx-auto w-full max-w-[1200px]">
                <SurveyNotifications
                    surveyId={survey.id}
                    description="Get notified whenever a survey result is submitted."
                />
            </div>
        </div>
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
                    onClick={() => openResumeSurveyDialog(survey, () => resumeSurvey())}
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
    const {
        survey,
        isAnyResultsLoading,
        resultsRequeryInProgress,
        processedSurveyStats,
        isSurveyHeadlineEnabled,
        hasActiveFilters,
        hasActiveAnswerFilters,
        hasActiveDateRange,
        propertyFilters,
    } = useValues(surveyLogic)
    const { clearFilters } = useActions(surveyLogic)

    const atLeastOneResponse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count
    const isRefreshingResults = resultsRequeryInProgress || isAnyResultsLoading

    if (!isRefreshingResults && !atLeastOneResponse) {
        return (
            <div className="px-4 pb-4">
                <div className="mx-auto w-full max-w-[1200px] space-y-4">
                    <SurveyResultsFiltersBar />
                    <SurveyNotificationsCallout surveyId={survey.id} />
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
                </div>
            </div>
        )
    }

    return (
        <div className="px-4 pb-4">
            <div className="mx-auto w-full max-w-[1200px] space-y-4">
                <SurveyResultsFiltersBar />
                <SurveyNotificationsCallout surveyId={survey.id} />
                <SurveyResultsRefreshStatus visible={isRefreshingResults} />
                <div
                    aria-busy={isRefreshingResults}
                    className={
                        isRefreshingResults
                            ? 'space-y-4 opacity-75 transition-opacity duration-200 ease-out'
                            : 'space-y-4 opacity-100 transition-opacity duration-200 ease-out'
                    }
                >
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
            </div>
        </div>
    )
}

function getUuidFromExpandableRecord(record: { result?: unknown }): string | undefined {
    const result = record?.result
    if (!Array.isArray(result)) {
        return undefined
    }
    const event = result[0] as { uuid?: string } | undefined
    return event?.uuid
}

// Don't trigger row expansion when the click originated from an interactive element inside the row.
const INTERACTIVE_SELECTOR = 'a, button, input, select, textarea, [role="button"], [data-skip-row-expand]'

function SurveyResponsesContent(): JSX.Element {
    const {
        dataTableQuery,
        survey,
        surveyLoading,
        archivedResponseUuids,
        expandedResponseUuids,
        isAnyResultsLoading,
        resultsRequeryInProgress,
    } = useValues(surveyLogic)
    const { setResponseExpanded, toggleResponseExpansion } = useActions(surveyLogic)
    const isInitialSurveyLoad = surveyLoading && survey.id === NEW_SURVEY.id
    const isRefreshingResults = resultsRequeryInProgress || isAnyResultsLoading
    const surveyColumnRenderers = useSurveyResponseColumns()

    return (
        <div className="px-4 pb-4 space-y-4">
            <SurveyResultsFiltersBar />
            <SurveyNotificationsCallout surveyId={survey.id} />
            <SurveyResultsRefreshStatus visible={isRefreshingResults} />
            {isInitialSurveyLoad ? (
                <LemonSkeleton />
            ) : (
                <div
                    aria-busy={isRefreshingResults}
                    className={
                        isRefreshingResults
                            ? 'survey-table-results opacity-75 transition-opacity duration-200 ease-out'
                            : 'survey-table-results opacity-100 transition-opacity duration-200 ease-out'
                    }
                >
                    <Query
                        query={dataTableQuery}
                        context={{
                            columns: surveyColumnRenderers,
                            rowProps: (record: unknown) => {
                                if (typeof record !== 'object' || !record || !('result' in record)) {
                                    return {}
                                }
                                const result = (record as { result?: unknown }).result
                                if (!Array.isArray(result)) {
                                    return {}
                                }
                                const uuid = (result[0] as { uuid?: string } | undefined)?.uuid
                                const isArchived = uuid ? archivedResponseUuids.has(uuid) : false
                                return {
                                    className: `cursor-pointer ${isArchived ? 'opacity-50' : ''}`.trim(),
                                    onClick: (e: React.MouseEvent<HTMLTableRowElement>) => {
                                        if (!uuid) {
                                            return
                                        }
                                        if ((e.target as HTMLElement).closest(INTERACTIVE_SELECTOR)) {
                                            return
                                        }
                                        toggleResponseExpansion(uuid)
                                    },
                                }
                            },
                            expandable: {
                                expandedRowRender: ({ result }) => <SurveyResponseExpandedRow result={result} />,
                                rowExpandable: ({ result }) => !!result,
                                isRowExpanded: (record) => {
                                    const uuid = getUuidFromExpandableRecord(record)
                                    return uuid ? expandedResponseUuids.has(uuid) : false
                                },
                                onRowExpand: (record) => {
                                    const uuid = getUuidFromExpandableRecord(record)
                                    if (uuid) {
                                        setResponseExpanded(uuid, true)
                                    }
                                },
                                onRowCollapse: (record) => {
                                    const uuid = getUuidFromExpandableRecord(record)
                                    if (uuid) {
                                        setResponseExpanded(uuid, false)
                                    }
                                },
                                noIndent: true,
                            },
                        }}
                    />
                </div>
            )}
        </div>
    )
}
