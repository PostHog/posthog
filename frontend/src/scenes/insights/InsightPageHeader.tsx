import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconInfo, IconPencil, IconShare, IconTrash, IconWarning } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessControlledLemonButton } from 'lib/components/AccessControlledLemonButton'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { AlertsButton } from 'lib/components/Alerts/AlertsButton'
import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { EditAlertModal } from 'lib/components/Alerts/views/EditAlertModal'
import { ManageAlertsModal } from 'lib/components/Alerts/views/ManageAlertsModal'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneAddToDashboardButton } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToDashboardButton'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneAlertsButton } from 'lib/components/Scenes/SceneAlertsButton'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { TemplateLinkSection } from 'lib/components/Sharing/TemplateLinkSection'
import {
    TEMPLATE_LINK_HEADING,
    TEMPLATE_LINK_PII_WARNING,
    TEMPLATE_LINK_TOOLTIP,
} from 'lib/components/Sharing/templateLinkMessages'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { isEmptyObject, isObject } from 'lib/utils'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { getLastNewFolder } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    ScenePanel,
    ScenePanelActions,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelMetaInfo,
} from '~/layout/scenes/SceneLayout'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isEventsQuery, isHogQLQuery } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ExporterFormat,
    InsightLogicProps,
    InsightShortId,
    ItemMode,
    QueryBasedInsightModel,
} from '~/types'

const RESOURCE_TYPE = 'insight'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    // insightSceneLogic
    const { insightMode, itemId, alertId, filtersOverride, variablesOverride } = useValues(insightSceneLogic)

    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const { insightProps, canEditInsight, insight, insightChanged, insightSaving, hasDashboardItemId, insightLoading } =
        useValues(insightLogic(insightLogicProps))
    const { setInsightMetadata, saveAs, saveInsight, duplicateInsight, reloadSavedInsights } = useActions(
        insightLogic(insightLogicProps)
    )

    // insightAlertsLogic
    const { loadAlerts } = useActions(
        insightAlertsLogic({
            insightLogicProps,
            insightId: insight.id as number,
        })
    )

    // insightDataLogic
    const { query, queryChanged, showQueryEditor, showDebugPanel, hogQL, exportContext } = useValues(
        insightDataLogic(insightProps)
    )
    const { toggleQueryEditorPanel, toggleDebugPanel } = useActions(insightDataLogic(insightProps))
    const { createStaticCohort } = useActions(exportsLogic)

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
    const { tags: allExistingTags } = useValues(tagsModel)
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { push } = useActions(router)
    const [tags, setTags] = useState(insight.tags)
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const defaultInsightName =
        typeof lastBreadcrumb?.name === 'string' ? lastBreadcrumb.name : insight.name || insight.derived_name

    const [addToDashboardModalOpen, setAddToDashboardModalOpenModal] = useState<boolean>(false)

    const dashboardOverridesExist =
        (isObject(filtersOverride) && !isEmptyObject(filtersOverride)) ||
        (isObject(variablesOverride) && !isEmptyObject(variablesOverride))

    const overrideType = isObject(filtersOverride) ? 'filters' : 'variables'

    const showCohortButton =
        isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query)

    const siteUrl = preflight?.site_url || window.location.origin

    async function handleDuplicateInsight(): Promise<void> {
        // We do not want to duplicate the dashboard filters that might be included in this insight
        // Ideally we would store those separately and be able to remove them on duplicate or edit, but current we merge them
        // irreversibly in apply_dashboard_filters and return that to the front-end
        if (insight.short_id) {
            const cleanInsight = await insightsApi.getByShortId(insight.short_id)
            if (cleanInsight) {
                duplicateInsight(cleanInsight, true)
                return
            }
        }
        // Fallback to original behavior if load failed
        duplicateInsight(insight as QueryBasedInsightModel, true)
    }

    return (
        <>
            {hasDashboardItemId && (
                <>
                    <SubscriptionsModal
                        isOpen={insightMode === ItemMode.Subscriptions}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        subscriptionId={typeof itemId === 'number' || itemId === 'new' ? itemId : null}
                    />
                    <SharingModal
                        title="Insight sharing"
                        isOpen={insightMode === ItemMode.Sharing}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        insight={insight}
                        previewIframe
                        userAccessLevel={insight.user_access_level}
                    />
                    <AddToDashboardModal
                        isOpen={addToDashboardModalOpen}
                        closeModal={() => setAddToDashboardModalOpenModal(false)}
                        insightProps={insightProps}
                        canEditInsight={canEditInsight}
                    />
                    {insightMode === ItemMode.Alerts && (
                        <ManageAlertsModal
                            onClose={() => push(urls.insightView(insight.short_id as InsightShortId))}
                            isOpen={insightMode === ItemMode.Alerts}
                            insightLogicProps={insightLogicProps}
                            insightId={insight.id as number}
                            insightShortId={insight.short_id as InsightShortId}
                        />
                    )}

                    {!!alertId && insight.id && (
                        <EditAlertModal
                            onClose={() => push(urls.insightAlerts(insight.short_id as InsightShortId))}
                            isOpen={!!alertId}
                            alertId={alertId === null || alertId === 'new' ? undefined : alertId}
                            insightShortId={insight.short_id as InsightShortId}
                            insightId={insight.id}
                            onEditSuccess={() => {
                                loadAlerts()
                                push(urls.insightAlerts(insight.short_id as InsightShortId))
                            }}
                            insightLogicProps={insightLogicProps}
                        />
                    )}
                    <NewDashboardModal />
                </>
            )}
            <PageHeader
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        {insightMode === ItemMode.Edit && hasDashboardItemId && (
                            <LemonButton
                                type="secondary"
                                onClick={() => setInsightMode(ItemMode.View, null)}
                                data-attr="insight-cancel-edit-button"
                            >
                                Cancel
                            </LemonButton>
                        )}

                        {!newSceneLayout && insightMode !== ItemMode.Edit && hasDashboardItemId && (
                            <>
                                <AlertsButton
                                    insight={insight}
                                    insightLogicProps={insightLogicProps}
                                    type="secondary"
                                    text="Alerts"
                                />
                                <NotebookSelectButton
                                    resource={{
                                        type: NotebookNodeType.Query,
                                        attrs: {
                                            query: {
                                                kind: NodeKind.SavedInsightNode,
                                                shortId: insight.short_id,
                                            },
                                        },
                                    }}
                                    type="secondary"
                                />
                                <AddToDashboard insight={insight} setOpenModal={setAddToDashboardModalOpenModal} />
                            </>
                        )}

                        {insightMode !== ItemMode.Edit ? (
                            canEditInsight && (
                                <AccessControlledLemonButton
                                    userAccessLevel={insight.user_access_level}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    resourceType={AccessControlResourceType.Insight}
                                    type="primary"
                                    icon={dashboardOverridesExist ? <IconWarning /> : undefined}
                                    tooltip={
                                        dashboardOverridesExist
                                            ? `This insight is being viewed with dashboard ${overrideType}. These will be discarded on edit.`
                                            : undefined
                                    }
                                    tooltipPlacement="bottom"
                                    onClick={() => {
                                        if (isDataVisualizationNode(query) && insight.short_id) {
                                            router.actions.push(urls.sqlEditor(undefined, undefined, insight.short_id))
                                        } else if (insight.short_id) {
                                            push(urls.insightEdit(insight.short_id))
                                        } else {
                                            setInsightMode(ItemMode.Edit, null)
                                        }
                                    }}
                                    data-attr="insight-edit-button"
                                >
                                    Edit
                                </AccessControlledLemonButton>
                            )
                        ) : (
                            <InsightSaveButton
                                saveAs={() => saveAs(undefined, undefined, 'Unfiled/Insights')}
                                saveInsight={(redirectToViewMode) =>
                                    insight.short_id
                                        ? saveInsight(redirectToViewMode)
                                        : saveInsight(redirectToViewMode, getLastNewFolder() ?? 'Unfiled/Insights')
                                }
                                isSaved={hasDashboardItemId}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged || queryChanged}
                            />
                        )}

                        {!newSceneLayout && (
                            <More
                                overlay={
                                    <>
                                        {hasDashboardItemId && (
                                            <>
                                                <LemonButton
                                                    onClick={() => void handleDuplicateInsight()}
                                                    fullWidth
                                                    data-attr="duplicate-insight-from-insight-view"
                                                >
                                                    Duplicate
                                                </LemonButton>

                                                <LemonButton
                                                    onClick={() =>
                                                        setInsightMetadata({
                                                            favorited: !insight.favorited,
                                                        })
                                                    }
                                                    fullWidth
                                                >
                                                    {insight.favorited ? 'Remove from favorites' : 'Add to favorites'}
                                                </LemonButton>

                                                <LemonButton
                                                    onClick={() => setAddToDashboardModalOpenModal(true)}
                                                    fullWidth
                                                >
                                                    Add to dashboard
                                                </LemonButton>

                                                <LemonDivider />

                                                <LemonButton
                                                    onClick={() =>
                                                        insight.short_id
                                                            ? push(urls.insightSharing(insight.short_id))
                                                            : null
                                                    }
                                                    fullWidth
                                                >
                                                    Share or embed
                                                </LemonButton>

                                                <SubscribeButton insightShortId={insight.short_id} />

                                                {exportContext ? (
                                                    <ExportButton
                                                        fullWidth
                                                        items={[
                                                            {
                                                                export_format: ExporterFormat.PNG,
                                                                insight: insight.id,
                                                            },
                                                            {
                                                                export_format: ExporterFormat.CSV,
                                                                export_context: exportContext,
                                                            },
                                                            {
                                                                export_format: ExporterFormat.XLSX,
                                                                export_context: exportContext,
                                                            },
                                                        ]}
                                                    />
                                                ) : null}

                                                <LemonDivider />
                                            </>
                                        )}

                                        {!insight.short_id && (
                                            <LemonButton
                                                onClick={() => {
                                                    const templateLink = getInsightDefinitionUrl({ query }, siteUrl)
                                                    LemonDialog.open({
                                                        title: (
                                                            <span className="flex items-center gap-2">
                                                                <TitleWithIcon
                                                                    icon={
                                                                        <Tooltip title={TEMPLATE_LINK_TOOLTIP}>
                                                                            <IconInfo />
                                                                        </Tooltip>
                                                                    }
                                                                >
                                                                    <b>{TEMPLATE_LINK_HEADING}</b>
                                                                </TitleWithIcon>
                                                            </span>
                                                        ),
                                                        content: (
                                                            <TemplateLinkSection
                                                                templateLink={templateLink}
                                                                heading={undefined}
                                                                tooltip={undefined}
                                                                piiWarning={TEMPLATE_LINK_PII_WARNING}
                                                            />
                                                        ),
                                                        width: 600,
                                                        primaryButton: {
                                                            children: 'Close',
                                                            type: 'secondary',
                                                        },
                                                    })
                                                }}
                                                fullWidth
                                            >
                                                Share as template
                                            </LemonButton>
                                        )}

                                        <LemonSwitch
                                            data-attr={`${showQueryEditor ? 'hide' : 'show'}-insight-source`}
                                            className="px-2 py-1"
                                            checked={showQueryEditor}
                                            onChange={() => {
                                                // for an existing insight in view mode
                                                if (hasDashboardItemId && insightMode !== ItemMode.Edit) {
                                                    // enter edit mode
                                                    setInsightMode(ItemMode.Edit, null)

                                                    // exit early if query editor doesn't need to be toggled
                                                    if (showQueryEditor) {
                                                        return
                                                    }
                                                }
                                                toggleQueryEditorPanel()
                                            }}
                                            fullWidth
                                            label="View source"
                                        />

                                        {hasDashboardItemId &&
                                        (user?.is_staff || user?.is_impersonated || !preflight?.cloud) ? (
                                            <LemonSwitch
                                                data-attr="toggle-debug-panel"
                                                className="px-2 py-1"
                                                checked={showDebugPanel}
                                                onChange={() => {
                                                    toggleDebugPanel()
                                                }}
                                                fullWidth
                                                label="Debug panel"
                                            />
                                        ) : null}

                                        {(hogQL || showCohortButton) && <LemonDivider />}
                                        {hogQL &&
                                            !isHogQLQuery(query) &&
                                            !(isDataVisualizationNode(query) && isHogQLQuery(query.source)) && (
                                                <LemonButton
                                                    data-attr="edit-insight-sql"
                                                    onClick={() => {
                                                        router.actions.push(urls.sqlEditor(hogQL))
                                                    }}
                                                    fullWidth
                                                >
                                                    Edit SQL directly
                                                </LemonButton>
                                            )}
                                        {hogQL && showCohortButton && (
                                            <LemonButton
                                                data-attr="edit-insight-sql"
                                                onClick={() => {
                                                    LemonDialog.openForm({
                                                        title: 'Save as static cohort',
                                                        description: (
                                                            <div className="mt-2">
                                                                Your query must export a <code>person_id</code>,{' '}
                                                                <code>actor_id</code> or <code>id</code> column, which
                                                                must match the <code>id</code> of the{' '}
                                                                <code>persons</code> table
                                                            </div>
                                                        ),
                                                        initialValues: {
                                                            name: '',
                                                        },
                                                        content: (
                                                            <LemonField name="name">
                                                                <LemonInput
                                                                    data-attr="insight-name"
                                                                    placeholder="Name of the new cohort"
                                                                    autoFocus
                                                                />
                                                            </LemonField>
                                                        ),
                                                        errors: {
                                                            name: (name) =>
                                                                !name ? 'You must enter a name' : undefined,
                                                        },
                                                        onSubmit: async ({ name }) => {
                                                            createStaticCohort(name, {
                                                                kind: NodeKind.HogQLQuery,
                                                                query: hogQL,
                                                            })
                                                        },
                                                    })
                                                }}
                                                fullWidth
                                            >
                                                Save as static cohort
                                            </LemonButton>
                                        )}

                                        {hasDashboardItemId && (
                                            <>
                                                <LemonDivider />
                                                <AccessControlledLemonButton
                                                    userAccessLevel={insight.user_access_level}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                    resourceType={AccessControlResourceType.Insight}
                                                    status="danger"
                                                    onClick={() =>
                                                        void deleteInsightWithUndo({
                                                            object: insight as QueryBasedInsightModel,
                                                            endpoint: `projects/${currentProjectId}/insights`,
                                                            callback: () => {
                                                                reloadSavedInsights()
                                                                push(urls.savedInsights())
                                                            },
                                                        })
                                                    }
                                                    fullWidth
                                                >
                                                    Delete insight
                                                </AccessControlledLemonButton>
                                            </>
                                        )}
                                    </>
                                }
                            />
                        )}
                    </div>
                }
                caption={
                    <>
                        {!newSceneLayout && (
                            <>
                                {!!(canEditInsight || insight.description) && (
                                    <EditableField
                                        multiline
                                        markdown
                                        name="description"
                                        value={insight.description || ''}
                                        placeholder="Description (optional)"
                                        onSave={(value) => setInsightMetadata({ description: value })}
                                        saveOnBlur={true}
                                        maxLength={400} // Sync with Insight model
                                        mode={!canEditInsight ? 'view' : undefined}
                                        data-attr="insight-description"
                                        compactButtons
                                    />
                                )}
                                {canEditInsight ? (
                                    <ObjectTags
                                        tags={tags ?? []}
                                        saving={insightSaving}
                                        onChange={(tags) => setTags(tags)}
                                        onBlur={() => {
                                            if (tags !== insight.tags) {
                                                setInsightMetadata({ tags: tags ?? [] })
                                            }
                                        }}
                                        tagsAvailable={allExistingTags}
                                        className="mt-2"
                                        data-attr="insight-tags"
                                    />
                                ) : tags?.length ? (
                                    <ObjectTags
                                        tags={tags}
                                        saving={insightSaving}
                                        className="mt-2"
                                        data-attr="insight-tags"
                                        staticOnly
                                    />
                                ) : null}
                                <UserActivityIndicator
                                    at={insight.last_modified_at}
                                    by={insight.last_modified_by}
                                    className="mt-2"
                                />
                            </>
                        )}
                    </>
                }
                tabbedPage={insightMode === ItemMode.Edit} // Insight type tabs are only shown in edit mode
            />

            <ScenePanel>
                <>
                    <ScenePanelCommonActions>
                        <SceneCommonButtons
                            dataAttrKey={RESOURCE_TYPE}
                            duplicate={
                                hasDashboardItemId
                                    ? {
                                          onClick: () => void handleDuplicateInsight(),
                                      }
                                    : undefined
                            }
                            favorite={{
                                active: insight.favorited,
                                onClick: () => {
                                    setInsightMetadata({ favorited: !insight.favorited })
                                },
                            }}
                        />
                    </ScenePanelCommonActions>
                    <ScenePanelMetaInfo>
                        <SceneTags
                            onSave={(tags) => {
                                setInsightMetadata({ tags })
                                setTags(tags)
                            }}
                            tags={tags}
                            tagsAvailable={allExistingTags}
                            dataAttrKey={RESOURCE_TYPE}
                            canEdit={canEditInsight}
                        />

                        <SceneFile dataAttrKey={RESOURCE_TYPE} />
                        <SceneActivityIndicator
                            at={insight.last_modified_at}
                            by={insight.last_modified_by}
                            prefix="Last modified"
                        />
                    </ScenePanelMetaInfo>

                    <ScenePanelDivider />

                    <ScenePanelActions>
                        {hasDashboardItemId && <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />}

                        <SceneAddToNotebookDropdownMenu shortId={insight.short_id} dataAttrKey={RESOURCE_TYPE} />
                        <SceneAddToDashboardButton
                            dashboard={
                                hasDashboardItemId
                                    ? {
                                          onClick: () => {
                                              setAddToDashboardModalOpenModal(true)
                                          },
                                      }
                                    : undefined
                            }
                            dataAttrKey={RESOURCE_TYPE}
                        />

                        {hasDashboardItemId && <SceneSubscribeButton insight={insight} dataAttrKey={RESOURCE_TYPE} />}
                        {hasDashboardItemId && insight?.id && insight?.short_id && (
                            <SceneAlertsButton
                                insightId={insight?.id}
                                insightShortId={insight.short_id as InsightShortId}
                                insightLogicProps={insightLogicProps}
                                dataAttrKey={RESOURCE_TYPE}
                            />
                        )}

                        {hasDashboardItemId && (
                            <SceneShareButton
                                buttonProps={{
                                    menuItem: true,
                                    onClick: () =>
                                        insight.short_id ? push(urls.insightSharing(insight.short_id)) : null,
                                }}
                                dataAttrKey={RESOURCE_TYPE}
                            />
                        )}

                        {!insight.short_id && (
                            <ButtonPrimitive
                                onClick={() => {
                                    const templateLink = getInsightDefinitionUrl({ query }, siteUrl)
                                    LemonDialog.open({
                                        title: (
                                            <span className="flex items-center gap-2">
                                                <TitleWithIcon
                                                    icon={
                                                        <Tooltip title={TEMPLATE_LINK_TOOLTIP}>
                                                            <IconInfo />
                                                        </Tooltip>
                                                    }
                                                >
                                                    <b>{TEMPLATE_LINK_HEADING}</b>
                                                </TitleWithIcon>
                                            </span>
                                        ),
                                        content: (
                                            <TemplateLinkSection
                                                templateLink={templateLink}
                                                heading={undefined}
                                                tooltip={undefined}
                                                piiWarning={TEMPLATE_LINK_PII_WARNING}
                                            />
                                        ),
                                        width: 600,
                                        primaryButton: {
                                            children: 'Close',
                                            type: 'secondary',
                                        },
                                    })
                                }}
                                menuItem
                            >
                                <IconShare />
                                Share as template...
                            </ButtonPrimitive>
                        )}

                        {exportContext ? (
                            <SceneExportDropdownMenu
                                dropdownMenuItems={[
                                    {
                                        format: ExporterFormat.PNG,
                                        insight: insight.id,
                                        dataAttr: `${RESOURCE_TYPE}-export-png`,
                                    },
                                    {
                                        format: ExporterFormat.CSV,
                                        context: exportContext,
                                        dataAttr: `${RESOURCE_TYPE}-export-csv`,
                                    },
                                    {
                                        format: ExporterFormat.XLSX,
                                        context: exportContext,
                                        dataAttr: `${RESOURCE_TYPE}-export-xlsx`,
                                    },
                                ]}
                            />
                        ) : null}

                        {hogQL &&
                            !isHogQLQuery(query) &&
                            !(isDataVisualizationNode(query) && isHogQLQuery(query.source)) && (
                                <ButtonPrimitive
                                    data-attr={`${RESOURCE_TYPE}-edit-sql`}
                                    onClick={() => {
                                        router.actions.push(urls.sqlEditor(hogQL))
                                    }}
                                    menuItem
                                >
                                    <IconPencil />
                                    Edit in SQL editor
                                </ButtonPrimitive>
                            )}

                        {hogQL && showCohortButton && (
                            <ButtonPrimitive
                                data-attr={`${RESOURCE_TYPE}-save-as-cohort`}
                                onClick={() => {
                                    LemonDialog.openForm({
                                        title: 'Save as static cohort',
                                        description: (
                                            <div className="mt-2">
                                                Your query must export a <code>person_id</code>, <code>actor_id</code>{' '}
                                                or <code>id</code> column, which must match the <code>id</code> of the{' '}
                                                <code>persons</code> table
                                            </div>
                                        ),
                                        initialValues: {
                                            name: '',
                                        },
                                        content: (
                                            <LemonField name="name">
                                                <LemonInput
                                                    data-attr={`${RESOURCE_TYPE}-save-as-cohort-name`}
                                                    placeholder="Name of the new cohort"
                                                    autoFocus
                                                />
                                            </LemonField>
                                        ),
                                        errors: {
                                            name: (name) => (!name ? 'You must enter a name' : undefined),
                                        },
                                        onSubmit: async ({ name }) => {
                                            createStaticCohort(name, {
                                                kind: NodeKind.HogQLQuery,
                                                query: hogQL,
                                            })
                                        },
                                    })
                                }}
                            >
                                Save as static cohort
                            </ButtonPrimitive>
                        )}

                        <ScenePanelDivider />

                        <LemonSwitch
                            data-attr={`${RESOURCE_TYPE}-${showQueryEditor ? 'hide' : 'show'}-source`}
                            className="px-2 py-1"
                            checked={showQueryEditor}
                            onChange={() => {
                                // for an existing insight in view mode
                                if (hasDashboardItemId && insightMode !== ItemMode.Edit) {
                                    // enter edit mode
                                    setInsightMode(ItemMode.Edit, null)

                                    // exit early if query editor doesn't need to be toggled
                                    if (showQueryEditor) {
                                        return
                                    }
                                }
                                toggleQueryEditorPanel()
                            }}
                            fullWidth
                            label="View source"
                        />

                        {hasDashboardItemId && (user?.is_staff || user?.is_impersonated || !preflight?.cloud) ? (
                            <LemonSwitch
                                data-attr={`${RESOURCE_TYPE}-toggle-debug-panel`}
                                className="px-2 py-1"
                                checked={showDebugPanel}
                                onChange={() => {
                                    toggleDebugPanel()
                                }}
                                fullWidth
                                label="Debug panel"
                            />
                        ) : null}

                        {hasDashboardItemId && (
                            <>
                                <ScenePanelDivider />
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Notebook}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    {({ disabledReason }) => (
                                        <ButtonPrimitive
                                            menuItem
                                            variant="danger"
                                            disabled={!!disabledReason}
                                            {...(disabledReason && { tooltip: disabledReason })}
                                            data-attr={`${RESOURCE_TYPE}-delete`}
                                            onClick={() =>
                                                void deleteInsightWithUndo({
                                                    object: insight as QueryBasedInsightModel,
                                                    endpoint: `projects/${currentProjectId}/insights`,
                                                    callback: () => {
                                                        reloadSavedInsights()
                                                        push(urls.savedInsights())
                                                    },
                                                })
                                            }
                                        >
                                            <IconTrash />
                                            Delete insight
                                        </ButtonPrimitive>
                                    )}
                                </AccessControlAction>
                            </>
                        )}
                    </ScenePanelActions>
                </>
            </ScenePanel>

            <SceneTitleSection
                name={defaultInsightName || ''}
                description={insight?.description || ''}
                resourceType={{
                    type: 'product_analytics',
                }}
                onNameChange={(name) => {
                    setInsightMetadata({ name })
                }}
                onDescriptionChange={(description) => {
                    setInsightMetadata({ description })
                }}
                canEdit={canEditInsight}
                isLoading={insightLoading && !insight?.id}
                forceEdit={insightMode === ItemMode.Edit}
                // Renaming insights is too fast, so we need to debounce it
                renameDebounceMs={1000}
            />
            <SceneDivider />
        </>
    )
}
