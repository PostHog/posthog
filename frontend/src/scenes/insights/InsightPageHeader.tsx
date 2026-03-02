import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconCode2, IconInfo, IconPencil, IconPeople, IconShare, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { areAlertsSupportedForInsight } from 'lib/components/Alerts/insightAlertsLogic'
import { EditAlertModal } from 'lib/components/Alerts/views/EditAlertModal'
import { ManageAlertsModal } from 'lib/components/Alerts/views/ManageAlertsModal'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { SceneAddToDashboardButton } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToDashboardButton'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneAlertsButton } from 'lib/components/Scenes/SceneAlertsButton'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFavorite } from 'lib/components/Scenes/SceneFavorite'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import {
    TEMPLATE_LINK_HEADING,
    TEMPLATE_LINK_PII_WARNING,
    TEMPLATE_LINK_TOOLTIP,
} from 'lib/components/Sharing/templateLinkMessages'
import { TemplateLinkSection } from 'lib/components/Sharing/TemplateLinkSection'
import { SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { getLastNewFolder } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'
import { HogQLQuery, InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
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

import { EndpointFromInsightModal } from 'products/endpoints/frontend/EndpointFromInsightModal'
import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'

import { getInsightIconTypeFromQuery, getOverrideWarningPropsForButton } from './utils'

const RESOURCE_TYPE = 'insight'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    // insightSceneLogic
    const { insightMode, itemId, alertId, filtersOverride, variablesOverride, dashboardId } =
        useValues(insightSceneLogic)

    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const {
        insightProps,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        isSavingTags,
        hasDashboardItemId,
        insightLoading,
        derivedName,
    } = useValues(insightLogic(insightLogicProps))
    const { setInsightMetadata, setInsightMetadataLocal, saveAs, saveInsight, duplicateInsight, deleteInsight } =
        useActions(insightLogic(insightLogicProps))

    // insightDataLogic
    const {
        query,
        queryChanged,
        showQueryEditor,
        showDebugPanel,
        hogQL,
        exportContext,
        hogQLVariables,
        insightQuery,
        insightData,
        generatedInsightNameLoading,
    } = useValues(insightDataLogic(insightProps))
    const { toggleQueryEditorPanel, toggleDebugPanel, cancelChanges, generateInsightName } = useActions(
        insightDataLogic(insightProps)
    )
    const { createStaticCohort } = useActions(exportsLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const canAccessAutoname = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_AUTONAME_INSIGHTS_WITH_AI]

    // endpointLogic
    const { openCreateFromInsightModal } = useActions(endpointLogic({ tabId: insightProps.tabId || '' }))

    // other logics
    const { tags: allExistingTags } = useValues(tagsModel)
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { push } = useActions(router)
    const [tags, setTags] = useState(insight.tags)
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const defaultInsightName =
        typeof lastBreadcrumb?.name === 'string' ? lastBreadcrumb.name : insight.name || insight.derived_name

    const [addToDashboardModalOpen, setAddToDashboardModalOpenModal] = useState<boolean>(false)
    const [terraformModalOpen, setTerraformModalOpen] = useState<boolean>(false)

    const showCohortButton =
        isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query)

    const siteUrl = preflight?.site_url || window.location.origin

    const canCreateAlertForInsight = areAlertsSupportedForInsight(query)

    useMaxTool({
        identifier: 'upsert_alert',
        active: canCreateAlertForInsight && hasDashboardItemId && !!insight.id,
        context: useMemo(
            () => ({
                insight_id: insight.id,
                insight_short_id: insight.short_id,
                insight_name: insight.name || insight.derived_name,
            }),
            [insight.id, insight.short_id, insight.name, insight.derived_name]
        ),
    })

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
                        cachedResults={insightData}
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
                            canCreateAlertForInsight={canCreateAlertForInsight}
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
                                push(urls.insightAlerts(insight.short_id as InsightShortId))
                            }}
                            insightLogicProps={insightLogicProps}
                        />
                    )}
                    <NewDashboardModal />
                    <EndpointFromInsightModal
                        tabId={insightProps.tabId || ''}
                        insightQuery={insightQuery as HogQLQuery | InsightQueryNode}
                        insightShortId={insight.short_id}
                    />
                </>
            )}

            <TerraformExportModal
                isOpen={terraformModalOpen}
                onClose={() => setTerraformModalOpen(false)}
                resource={{ type: 'insight', data: { ...insight, query, derived_name: derivedName } }}
            />

            <ScenePanel>
                <>
                    <ScenePanelInfoSection>
                        <SceneTags
                            onSave={(tags) => {
                                setInsightMetadata({ tags })
                                setTags(tags)
                            }}
                            tags={tags}
                            tagsAvailable={allExistingTags}
                            dataAttrKey={RESOURCE_TYPE}
                            canEdit={canEditInsight}
                            loading={isSavingTags}
                        />

                        <SceneFile dataAttrKey={RESOURCE_TYPE} />
                        <SceneActivityIndicator
                            at={insight.last_modified_at}
                            by={insight.last_modified_by}
                            prefix="Last modified"
                        />
                    </ScenePanelInfoSection>

                    <ScenePanelDivider />

                    <ScenePanelActionsSection>
                        <SceneDuplicate
                            dataAttrKey={RESOURCE_TYPE}
                            onClick={() => duplicateInsight(insight as QueryBasedInsightModel, true)}
                        />
                        <SceneFavorite
                            dataAttrKey={RESOURCE_TYPE}
                            onClick={() => {
                                setInsightMetadata({ favorited: !insight.favorited })
                            }}
                            isFavorited={insight.favorited ?? false}
                        />

                        {insight.short_id && (
                            <SceneAddToNotebookDropdownMenu shortId={insight.short_id} dataAttrKey={RESOURCE_TYPE} />
                        )}
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

                        {exportContext && insight.short_id != null ? (
                            <SceneExportDropdownMenu
                                dropdownMenuItems={[
                                    {
                                        format: ExporterFormat.PNG,
                                        insight: insight.id,
                                        context: exportContext,
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

                        <ButtonPrimitive
                            onClick={() => setTerraformModalOpen(true)}
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-manage-terraform`}
                        >
                            <IconCode2 />
                            Manage with Terraform
                        </ButtonPrimitive>

                        {hasDashboardItemId && featureFlags[FEATURE_FLAGS.ENDPOINTS] ? (
                            <ButtonPrimitive
                                onClick={() => {
                                    openCreateFromInsightModal()
                                }}
                                menuItem
                            >
                                <IconCode2 />
                                Create endpoint
                            </ButtonPrimitive>
                        ) : null}
                        {hogQL &&
                            !isHogQLQuery(query) &&
                            !(isDataVisualizationNode(query) && isHogQLQuery(query.source)) && (
                                <Link
                                    to={urls.sqlEditor({ query: hogQL })}
                                    buttonProps={{
                                        'data-attr': `${RESOURCE_TYPE}-edit-sql`,
                                        menuItem: true,
                                    }}
                                >
                                    <IconPencil />
                                    Edit in SQL editor
                                </Link>
                            )}

                        {hogQL && showCohortButton && (
                            <ButtonPrimitive
                                data-attr={`${RESOURCE_TYPE}-save-as-cohort`}
                                onClick={() => {
                                    LemonDialog.openForm({
                                        title: 'Save as static cohort',
                                        description: (
                                            <>
                                                <div className="mt-2">
                                                    Your query must export a <code>person_id</code>,{' '}
                                                    <code>actor_id</code>, <code>id</code>, or <code>distinct_id</code>{' '}
                                                    column. The <code>person_id</code>, <code>actor_id</code>, and{' '}
                                                    <code>id</code> columns must match the <code>id</code> of the{' '}
                                                    <code>persons</code> table, while <code>distinct_id</code> will be
                                                    automatically resolved to the corresponding person.
                                                </div>
                                            </>
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
                                                variables: hogQLVariables,
                                            })
                                        },
                                    })
                                }}
                                menuItem
                            >
                                <IconPeople />
                                Save as static cohort
                            </ButtonPrimitive>
                        )}
                        {hasDashboardItemId && <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />}
                    </ScenePanelActionsSection>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
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
                    </ScenePanelActionsSection>
                    {hasDashboardItemId && (
                        <>
                            <ScenePanelDivider />
                            <ScenePanelActionsSection>
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
                                            onClick={() => deleteInsight(dashboardId ?? null)}
                                        >
                                            <IconTrash />
                                            Delete insight
                                        </ButtonPrimitive>
                                    )}
                                </AccessControlAction>
                            </ScenePanelActionsSection>
                        </>
                    )}
                </>
            </ScenePanel>

            <SceneTitleSection
                name={defaultInsightName || ''}
                description={insight?.description || ''}
                resourceType={{
                    type: getInsightIconTypeFromQuery(query),
                }}
                onNameChange={(name) => {
                    if (insightMode === ItemMode.Edit) {
                        setInsightMetadataLocal({ name })
                    } else {
                        setInsightMetadata({ name })
                    }
                }}
                onDescriptionChange={(description) => {
                    if (insightMode === ItemMode.Edit) {
                        setInsightMetadataLocal({ description })
                    } else {
                        setInsightMetadata({ description })
                    }
                }}
                onGenerateName={canAccessAutoname && insightQuery ? generateInsightName : undefined}
                isGeneratingName={canAccessAutoname && generatedInsightNameLoading}
                canEdit={canEditInsight}
                isLoading={insightLoading && !insight?.id}
                forceEdit={insightMode === ItemMode.Edit}
                renameDebounceMs={0}
                // Use onBlur-only saves to prevent autosave while typing
                saveOnBlur
                actions={
                    <>
                        {insightMode === ItemMode.Edit && hasDashboardItemId && (
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    cancelChanges()
                                    setInsightMode(ItemMode.View, null)
                                }}
                                data-attr="insight-cancel-edit-button"
                                size="small"
                            >
                                Cancel
                            </LemonButton>
                        )}

                        {insightMode !== ItemMode.Edit ? (
                            canEditInsight && (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        tooltipPlacement="bottom"
                                        onClick={() => {
                                            if (isDataVisualizationNode(query) && insight.short_id) {
                                                router.actions.push(
                                                    urls.sqlEditor({ insightShortId: insight.short_id })
                                                )
                                            } else if (insight.short_id) {
                                                const editUrl = dashboardId
                                                    ? combineUrl(urls.insightEdit(insight.short_id), {
                                                          dashboard: dashboardId,
                                                      }).url
                                                    : urls.insightEdit(insight.short_id)
                                                push(editUrl)
                                            } else {
                                                setInsightMode(ItemMode.Edit, null)
                                            }
                                        }}
                                        {...getOverrideWarningPropsForButton(filtersOverride, variablesOverride)}
                                        data-attr="insight-edit-button"
                                    >
                                        Edit
                                    </LemonButton>
                                </AccessControlAction>
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
                    </>
                }
            />
        </>
    )
}
