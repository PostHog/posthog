import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconArchive, IconCopy, IconPlusSmall, IconRewind, IconTrash } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessDenied } from 'lib/components/AccessDenied'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMenuBarAddToNotebook } from 'lib/components/Scenes/SceneMenuBarAddToNotebook'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import 'lib/lemon-ui/Lettermark'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { EmptyDashboardComponent } from 'scenes/dashboard/EmptyDashboardComponent'
import { FeatureFlagPermissions } from 'scenes/FeatureFlagPermissions'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { SceneExport } from 'scenes/sceneTypes'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { getSurveyForFeatureFlagVariant } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    AnyPropertyFilter,
    DashboardPlacement,
    DashboardType,
    EarlyAccessFeatureStage,
    FeatureFlagType,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
} from '~/types'

import { openFeatureFlagArchiveDialog } from './featureFlagArchiveDialog'
import { openFeatureFlagDeleteDialog } from './featureFlagDeleteDialog'
import { FeatureFlagEvaluationContexts } from './FeatureFlagEvaluationContexts'
import { ExperimentsTab } from './FeatureFlagExperimentsTab'
import { FeedbackTab } from './FeatureFlagFeedbackTab'
import { FeatureFlagForm } from './FeatureFlagForm'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagOverview } from './FeatureFlagOverview'
import FeatureFlagProjects from './FeatureFlagProjects'
import FeatureFlagSchedule from './FeatureFlagSchedule'
import { FeatureFlagsTab, featureFlagsLogic } from './featureFlagsLogic'
import { FeatureFlagTestingTab } from './FeatureFlagTestingTab'

const RESOURCE_TYPE = 'feature_flag'

export const scene: SceneExport<FeatureFlagLogicProps> = {
    component: FeatureFlag,
    logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

export function FeatureFlag({ id }: FeatureFlagLogicProps): JSX.Element {
    const {
        props,
        featureFlag,
        featureFlagLoading,
        featureFlagMissing,
        isEditingFlag,
        activeTab,
        accessDeniedToFeatureFlag,
        earlyAccessFeaturesList,
        featureFlagActiveUpdateLoading,
        dependentFlags,
    } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const {
        deleteFeatureFlag,
        restoreFeatureFlag,
        editFeatureFlag,
        createStaticCohort,
        setActiveTab,
        updateFlag,
        saveFeatureFlag,
        saveDescriptionInline,
        saveTagsInline,
        updateFeatureFlagArchived,
    } = useActions(featureFlagLogic)

    const { tags } = useValues(tagsModel)
    const { currentTeamId } = useValues(teamLogic)
    const { reportUserFeedbackButtonClicked } = useActions(eventUsageLogic)

    const [isQuickSurveyModalOpen, setIsQuickSurveyModalOpen] = useState(false)
    const [quickSurveyVariantKey, setQuickSurveyVariantKey] = useState<string | null>(null)

    const handleGetFeedback = (variantKey?: string): void => {
        const hasVariantSurvey = variantKey
            ? !!getSurveyForFeatureFlagVariant(variantKey, featureFlag.surveys ?? [])
            : featureFlag.surveys && featureFlag.surveys.length > 0

        reportUserFeedbackButtonClicked(SURVEY_CREATED_SOURCE.FEATURE_FLAGS, {
            existingSurvey: hasVariantSurvey,
        })

        void addProductIntentForCrossSell({
            from: ProductKey.FEATURE_FLAGS,
            to: ProductKey.SURVEYS,
            intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
        })

        if (hasVariantSurvey) {
            setActiveTab(FeatureFlagsTab.FEEDBACK)
        } else {
            setIsQuickSurveyModalOpen(true)
            setQuickSurveyVariantKey(variantKey ?? null)
        }
    }

    const isNewFeatureFlag = id === 'new' || id === undefined

    useFileSystemLogView({
        type: 'feature_flag',
        ref: featureFlag?.id,
        enabled: Boolean(
            currentTeamId &&
            !featureFlagMissing &&
            !accessDeniedToFeatureFlag &&
            props.id !== 'new' &&
            props.id !== 'link' &&
            featureFlag?.id
        ),
    })

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }

    if (featureFlagLoading) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    // Use the form UI for creating new flags or editing existing flags.
    // For viewing existing flags (readonly), use the tabbed UI below.
    if (isNewFeatureFlag || isEditingFlag) {
        return <FeatureFlagForm id={id} />
    }

    if (accessDeniedToFeatureFlag) {
        return <AccessDenied object="feature flag" />
    }

    const earlyAccessFeature = earlyAccessFeaturesList?.find((f) => f.flagKey === featureFlag.key)

    const tabs = [
        {
            label: 'Overview',
            key: FeatureFlagsTab.OVERVIEW,
            content: <FeatureFlagOverview featureFlag={featureFlag} />,
        },
    ] as LemonTab<FeatureFlagsTab>[]

    if (id) {
        tabs.push({
            label: 'Usage',
            key: FeatureFlagsTab.USAGE,
            content: <UsageTab featureFlag={featureFlag} />,
        })

        tabs.push({
            label: 'Projects',
            key: FeatureFlagsTab.PROJECTS,
            content: <FeatureFlagProjects />,
        })

        tabs.push({
            label: 'Schedule',
            key: FeatureFlagsTab.SCHEDULE,
            content: <FeatureFlagSchedule />,
        })
    }

    if (featureFlag.id) {
        tabs.push({
            label: 'History',
            key: FeatureFlagsTab.HISTORY,
            content: <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={featureFlag.id} />,
        })
    }

    if (featureFlag.can_edit) {
        tabs.push({
            label: 'Permissions',
            key: FeatureFlagsTab.PERMISSIONS,
            content: <FeatureFlagPermissions featureFlag={featureFlag} />,
        })
    }

    tabs.push({
        label: 'User feedback',
        key: FeatureFlagsTab.FEEDBACK,
        content: <FeedbackTab featureFlag={featureFlag} />,
    })

    tabs.push({
        label: (
            <div className="flex flex-row">
                <div>Experiments</div>
            </div>
        ),
        key: FeatureFlagsTab.EXPERIMENTS,
        content: <ExperimentsTab featureFlag={featureFlag} />,
    })

    if (id) {
        tabs.push({
            label: (
                <div className="flex flex-row">
                    <div>Testing</div>
                    <LemonTag className="ml-2 float-right uppercase" type="primary">
                        New
                    </LemonTag>
                </div>
            ),
            key: FeatureFlagsTab.TESTING,
            content: <FeatureFlagTestingTab featureFlag={featureFlag} />,
        })
    }

    return (
        <>
            <div className="feature-flag">
                <ScenePanel>
                    <ScenePanelInfoSection>
                        {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] ? (
                            <FeatureFlagEvaluationContexts
                                tags={featureFlag.tags}
                                evaluationContexts={featureFlag.evaluation_contexts || []}
                                onSave={(updatedTags, updatedEvaluationContexts) => {
                                    const updatedFlag = {
                                        ...featureFlag,
                                        tags: updatedTags,
                                        evaluation_contexts: updatedEvaluationContexts,
                                    }
                                    updateFlag(updatedFlag)
                                    saveFeatureFlag(updatedFlag)
                                }}
                                tagsAvailable={tags.filter((tag: string) => !featureFlag.tags?.includes(tag))}
                                flagId={featureFlag.id}
                                context="sidebar"
                            />
                        ) : (
                            <SceneTags
                                onSave={(tags) => {
                                    const updatedFlag = { ...featureFlag, tags }
                                    updateFlag(updatedFlag)
                                    saveFeatureFlag(updatedFlag)
                                }}
                                canEdit
                                tags={featureFlag.tags}
                                tagsAvailable={tags.filter((tag: string) => !featureFlag.tags?.includes(tag))}
                                dataAttrKey={RESOURCE_TYPE}
                            />
                        )}

                        <SceneFile dataAttrKey={RESOURCE_TYPE} />
                    </ScenePanelInfoSection>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
                        <ButtonPrimitive
                            onClick={() => {
                                router.actions.push(urls.featureFlagNew({ sourceId: featureFlag.id }))
                            }}
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-duplicate`}
                        >
                            <IconCopy />
                            Duplicate
                        </ButtonPrimitive>
                        <SceneAddToNotebookDropdownMenu dataAttrKey={RESOURCE_TYPE} />
                        {featureFlags[FEATURE_FLAGS.FEATURE_FLAG_COHORT_CREATION] && (
                            <ButtonPrimitive
                                menuItem
                                data-attr={`${RESOURCE_TYPE}-create-cohort`}
                                onClick={() => createStaticCohort()}
                            >
                                <IconPlusSmall />
                                Create cohort
                            </ButtonPrimitive>
                        )}
                        <ButtonPrimitive
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-create-survey`}
                            onClick={() => handleGetFeedback()}
                        >
                            <IconPlusSmall />
                            Create survey
                        </ButtonPrimitive>
                    </ScenePanelActionsSection>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
                        {!featureFlag.deleted && (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.FeatureFlag}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                {({ disabledReason }) => (
                                    <ButtonPrimitive
                                        menuItem
                                        disabled={!!disabledReason || featureFlagActiveUpdateLoading}
                                        {...(disabledReason && { tooltip: disabledReason })}
                                        data-attr={
                                            featureFlag.archived ? 'unarchive-feature-flag' : 'archive-feature-flag'
                                        }
                                        onClick={() => {
                                            if (featureFlag.archived) {
                                                updateFeatureFlagArchived(false)
                                            } else {
                                                openFeatureFlagArchiveDialog(featureFlag, () =>
                                                    updateFeatureFlagArchived(true)
                                                )
                                            }
                                        }}
                                        disabledReasons={{
                                            "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator.":
                                                !featureFlag.can_edit,
                                        }}
                                    >
                                        {featureFlag.archived ? <IconRewind /> : <IconArchive />}
                                        {featureFlag.archived ? 'Unarchive' : 'Archive'} feature flag
                                    </ButtonPrimitive>
                                )}
                            </AccessControlAction>
                        )}
                        <AccessControlAction
                            resourceType={AccessControlResourceType.FeatureFlag}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {({ disabledReason }) => (
                                <ButtonPrimitive
                                    menuItem
                                    variant="danger"
                                    disabled={!!disabledReason}
                                    {...(disabledReason && { tooltip: disabledReason })}
                                    data-attr={featureFlag.deleted ? 'restore-feature-flag' : 'delete-feature-flag'}
                                    onClick={() => {
                                        if (featureFlag.deleted) {
                                            restoreFeatureFlag(featureFlag)
                                        } else {
                                            openFeatureFlagDeleteDialog(
                                                featureFlag,
                                                () => deleteFeatureFlag(featureFlag),
                                                dependentFlags
                                            )
                                        }
                                    }}
                                    disabledReasons={{
                                        "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator.":
                                            !featureFlag.can_edit,
                                    }}
                                >
                                    {featureFlag.deleted ? <IconRewind /> : <IconTrash />}
                                    {featureFlag.deleted ? 'Restore' : 'Delete'} feature flag
                                </ButtonPrimitive>
                            )}
                        </AccessControlAction>
                    </ScenePanelActionsSection>
                </ScenePanel>
                <SceneContent>
                    {featureFlag.id && (
                        <PendingChangeRequestBanner resourceType="feature_flag" resourceId={featureFlag.id} />
                    )}

                    {featureFlag.archived && (
                        <LemonBanner
                            type="warning"
                            action={
                                featureFlag.can_edit
                                    ? {
                                          children: 'Unarchive',
                                          onClick: () => updateFeatureFlagArchived(false),
                                          disabledReason: featureFlagActiveUpdateLoading ? 'Updating…' : undefined,
                                      }
                                    : undefined
                            }
                        >
                            This feature flag is archived. It's hidden from the flag list and can't be enabled — linked
                            experiments and surveys keep their data.
                        </LemonBanner>
                    )}
                    {earlyAccessFeature && earlyAccessFeature.stage === EarlyAccessFeatureStage.Concept && (
                        <LemonBanner type="info">
                            This feature flag is assigned to an early access feature in the{' '}
                            <LemonTag type="default" className="uppercase">
                                Concept
                            </LemonTag>{' '}
                            stage. All users who register interest will be assigned this feature flag. Gate your code
                            behind a different feature flag if you'd like to keep it hidden, and then switch your code
                            to this feature flag when you're ready to release to your early access users.
                        </LemonBanner>
                    )}
                    {featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR] && (
                        <SceneMenuBar>
                            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                                <SceneMenuBarSubMenu label="Create">
                                    {featureFlag.id && (
                                        <SceneMenuBarAddToNotebook
                                            dataAttrKey={RESOURCE_TYPE}
                                            notebookSelectButtonProps={{
                                                resource: {
                                                    type: NotebookNodeType.FeatureFlag,
                                                    attrs: { id: featureFlag.id },
                                                },
                                            }}
                                        />
                                    )}
                                    {featureFlags[FEATURE_FLAGS.FEATURE_FLAG_COHORT_CREATION] && (
                                        <SceneMenuBarItem
                                            onClick={() => createStaticCohort()}
                                            data-attr={`${RESOURCE_TYPE}-menubar-create-cohort`}
                                        >
                                            <IconPlusSmall />
                                            Cohort
                                        </SceneMenuBarItem>
                                    )}
                                    <SceneMenuBarItem
                                        opensFloatingUi
                                        onClick={() => handleGetFeedback()}
                                        data-attr={`${RESOURCE_TYPE}-menubar-create-survey`}
                                    >
                                        <IconPlusSmall />
                                        Survey
                                    </SceneMenuBarItem>
                                </SceneMenuBarSubMenu>
                                <SceneMenuBarSeparator />
                                <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                                <SceneMenuBarSeparator />
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.FeatureFlag}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    {({ disabledReason }) => (
                                        <SceneMenuBarItem
                                            variant="destructive"
                                            disabled={!!disabledReason}
                                            data-attr={
                                                featureFlag.deleted
                                                    ? `${RESOURCE_TYPE}-menubar-restore`
                                                    : `${RESOURCE_TYPE}-menubar-delete`
                                            }
                                            onClick={() => {
                                                if (featureFlag.deleted) {
                                                    restoreFeatureFlag(featureFlag)
                                                } else {
                                                    openFeatureFlagDeleteDialog(
                                                        featureFlag,
                                                        () => deleteFeatureFlag(featureFlag),
                                                        dependentFlags
                                                    )
                                                }
                                            }}
                                        >
                                            {featureFlag.deleted ? <IconRewind /> : <IconTrash />}
                                            {featureFlag.deleted ? 'Restore' : 'Delete'} feature flag
                                        </SceneMenuBarItem>
                                    )}
                                </AccessControlAction>
                            </SceneMenuBarMenu>
                            <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                                <SceneMenuBarItem
                                    onClick={() => {
                                        router.actions.push(urls.featureFlagNew({ sourceId: featureFlag.id }))
                                    }}
                                    data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                                >
                                    <IconCopy />
                                    Duplicate
                                </SceneMenuBarItem>
                            </SceneMenuBarMenu>
                            <SceneMenuBarPopover label="Metadata" dataAttr={`${RESOURCE_TYPE}-menubar-metadata`}>
                                <SceneTagsCombobox
                                    onSave={(updatedTags) => saveTagsInline(updatedTags)}
                                    canEdit
                                    tags={featureFlag.tags}
                                    tagsAvailable={tags.filter((tag: string) => !featureFlag.tags?.includes(tag))}
                                    dataAttrKey={RESOURCE_TYPE}
                                />
                            </SceneMenuBarPopover>
                        </SceneMenuBar>
                    )}
                    <SceneTitleSection
                        name={featureFlag.key}
                        description={featureFlag.name}
                        resourceType={{
                            type: featureFlag.active ? 'feature_flag' : 'feature_flag_off',
                        }}
                        canEdit={
                            !featureFlag.deleted &&
                            userHasAccess(
                                AccessControlResourceType.FeatureFlag,
                                AccessControlLevel.Editor,
                                featureFlag.user_access_level
                            )
                        }
                        saveOnBlur
                        onDescriptionChange={(newName) => {
                            saveDescriptionInline(newName)
                        }}
                        actions={
                            <AccessControlAction
                                resourceType={AccessControlResourceType.FeatureFlag}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={featureFlag.user_access_level}
                            >
                                {({ disabledReason }) => (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        disabledReason={disabledReason}
                                        onClick={() => editFeatureFlag(true)}
                                    >
                                        Edit
                                    </LemonButton>
                                )}
                            </AccessControlAction>
                        }
                    />
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(tab) => tab !== activeTab && setActiveTab(tab)}
                        tabs={tabs}
                        sceneInset
                    />
                </SceneContent>
            </div>
            <QuickSurveyModal
                context={{
                    type: QuickSurveyType.FEATURE_FLAG,
                    flag: featureFlag,
                    initialVariantKey: quickSurveyVariantKey,
                }}
                info="This survey will display to all users in this feature flag, filtered by any conditions you specify below."
                isOpen={isQuickSurveyModalOpen}
                onCancel={() => {
                    setIsQuickSurveyModalOpen(false)
                    setQuickSurveyVariantKey(null)
                }}
            />
        </>
    )
}

function ConnectedUsageDashboard({
    featureFlag,
    dashboardId,
    hasEnrichedAnalytics,
}: {
    featureFlag: FeatureFlagType
    dashboardId: number
    hasEnrichedAnalytics: boolean | undefined
}): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic({ id: dashboardId, placement: DashboardPlacement.FeatureFlag })) as {
        dashboard: DashboardType<QueryBasedInsightModel> | null
    }
    const { enrichAnalyticsNoticeAcknowledged } = useValues(featureFlagsLogic)
    const { closeEnrichAnalyticsNotice } = useActions(featureFlagsLogic)
    const { enrichUsageDashboard } = useActions(featureFlagLogic)

    useEffect(() => {
        if (
            dashboard &&
            hasEnrichedAnalytics &&
            !(dashboard.tiles?.find((tile) => (tile.insight?.name?.indexOf('Feature Viewed') ?? -1) > -1) !== undefined)
        ) {
            enrichUsageDashboard()
        }
    }, [dashboard, hasEnrichedAnalytics, enrichUsageDashboard])

    if (!dashboard) {
        return <LemonSkeleton className="h-60" />
    }

    return (
        <>
            {!hasEnrichedAnalytics && !enrichAnalyticsNoticeAcknowledged && (
                <LemonBanner type="info" className="mb-3" onClose={() => closeEnrichAnalyticsNotice()}>
                    Get richer insights automatically by{' '}
                    <Link to="https://posthog.com/docs/libraries/js/features#enriched-flag-analytics" target="_blank">
                        enabling enriched analytics for flags{' '}
                    </Link>
                </LemonBanner>
            )}
            <Dashboard
                id={dashboardId.toString()}
                placement={DashboardPlacement.FeatureFlag}
                backTo={{ url: urls.featureFlag(featureFlag.id!), name: featureFlag.key }}
            />
        </>
    )
}

function UsageTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const {
        key: featureFlagKey,
        usage_dashboard: dashboardId,
        has_enriched_analytics: hasEnrichedAnalytics,
    } = featureFlag
    const { generateUsageDashboard } = useActions(featureFlagLogic)
    const { featureFlagLoading } = useValues(featureFlagLogic)

    const propertyFilter: AnyPropertyFilter[] = [
        {
            key: '$feature_flag',
            type: PropertyFilterType.Event,
            value: featureFlagKey,
            operator: PropertyOperator.Exact,
        },
    ]

    if (featureFlag.deleted) {
        return (
            <div data-attr="feature-flag-usage-deleted-banner">
                <LemonBanner type="error">This feature flag has been deleted.</LemonBanner>
            </div>
        )
    }

    return (
        <div data-attr="feature-flag-usage-container">
            {dashboardId ? (
                <ConnectedUsageDashboard
                    featureFlag={featureFlag}
                    dashboardId={dashboardId}
                    hasEnrichedAnalytics={hasEnrichedAnalytics}
                />
            ) : (
                <div>
                    <b>Dashboard</b>
                    <div className="text-secondary mb-2">
                        There is currently no connected dashboard to this feature flag. If there was previously a
                        connected dashboard, it may have been deleted.
                    </div>
                    {featureFlagLoading ? (
                        <EmptyDashboardComponent loading={true} canEdit={false} />
                    ) : (
                        <LemonButton type="primary" onClick={() => generateUsageDashboard()}>
                            Generate Usage Dashboard
                        </LemonButton>
                    )}
                </div>
            )}
            <div className="mt-4 mb-4">
                <b>Log</b>
                <div className="text-secondary">{`Feature flag calls for "${featureFlagKey}" will appear here`}</div>
            </div>
            <Query
                query={{
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: [...defaultDataTableColumns(NodeKind.EventsQuery), 'properties.$feature_flag_response'],
                        event: '$feature_flag_called',
                        properties: propertyFilter,
                        after: '-30d',
                    },
                    full: false,
                    showDateRange: true,
                }}
            />
        </div>
    )
}
