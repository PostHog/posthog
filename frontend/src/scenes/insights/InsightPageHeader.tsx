import { IconCopy, IconGraph, IconInfo, IconPencil, IconWarning, IconX } from '@posthog/icons'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { AccessControlledLemonButton } from 'lib/components/AccessControlledLemonButton'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { AlertsButton } from 'lib/components/Alerts/AlertsButton'
import { insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { AlertType } from 'lib/components/Alerts/types'
import { EditAlertModal } from 'lib/components/Alerts/views/EditAlertModal'
import { ManageAlertsModal } from 'lib/components/Alerts/views/ManageAlertsModal'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { openSaveToModal } from 'lib/components/SaveTo/saveToLogic'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import {
    TEMPLATE_LINK_HEADING,
    TEMPLATE_LINK_PII_WARNING,
    TEMPLATE_LINK_TOOLTIP,
} from 'lib/components/Sharing/templateLinkMessages'
import { TemplateLinkSection } from 'lib/components/Sharing/TemplateLinkSection'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { isEmptyObject, isObject } from 'lib/utils'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'
import { useState } from 'react'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneHeader } from '~/layout/scenes/SceneHeader'
import { SceneHeaderItemType } from '~/layout/scenes/sceneHeaderLogic'
import { SceneLayout } from '~/layout/scenes/SceneLayout'
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
    NotebookNodeType,
    QueryBasedInsightModel,
} from '~/types'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    // insightSceneLogic
    const { insightMode, itemId, alertId, filtersOverride, variablesOverride } = useValues(insightSceneLogic)

    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const { insightProps, canEditInsight, insight, insightChanged, insightSaving, hasDashboardItemId } = useValues(
        insightLogic(insightLogicProps)
    )
    const { setInsightMetadata, saveAs, saveInsight } = useActions(insightLogic(insightLogicProps))

    // insightAlertsLogic
    const { loadAlerts } = useActions(
        insightAlertsLogic({
            insightLogicProps,
            insightId: insight.id as number,
        })
    )

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

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

    const [addToDashboardModalOpen, setAddToDashboardModalOpenModal] = useState<boolean>(false)

    const dashboardOverridesExist =
        (isObject(filtersOverride) && !isEmptyObject(filtersOverride)) ||
        (isObject(variablesOverride) && !isEmptyObject(variablesOverride))

    const overrideType = isObject(filtersOverride) ? 'filters' : 'variables'

    const showCohortButton =
        isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query)

    const siteUrl = preflight?.site_url || window.location.origin

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
                            onEditSuccess={(alertId: AlertType['id'] | undefined) => {
                                loadAlerts()
                                if (alertId) {
                                    push(urls.insightAlert(insight.short_id as InsightShortId, alertId))
                                } else {
                                    push(urls.insightAlerts(insight.short_id as InsightShortId))
                                }
                            }}
                            insightLogicProps={insightLogicProps}
                        />
                    )}
                    <NewDashboardModal />
                </>
            )}
            <SceneLayout
                className="saved-insights"
                header={
                    <SceneHeader
                        pageTitle={insight.name || ''}
                        pageIcon={<IconGraph />}
                        pageTitleEditable={true}
                        // handlePageTitleSubmit={(title) => {
                        //     console.log('saved title', title)
                        // }}
                        navItems={[
                            {
                                title: 'File',
                                id: 'file',
                                children: [
                                    ...(hasDashboardItemId
                                        ? [
                                              {
                                                  title: 'Duplicate',
                                                  id: 'duplicate',
                                                  icon: <IconCopy />,
                                                  type: 'link' as SceneHeaderItemType,
                                                  onClick: () => {
                                                      void (async () => {
                                                          // We do not want to duplicate the dashboard filters that might be included in this insight
                                                          // Ideally we would store those separately and be able to remove them on duplicate or edit, but current we merge them
                                                          // irreversibly in apply_dashboard_filters and return that to the front-end
                                                          if (insight.short_id) {
                                                              const cleanInsight = await insightsApi.getByShortId(
                                                                  insight.short_id
                                                              )
                                                              if (cleanInsight) {
                                                                  duplicateInsight(cleanInsight, true)
                                                                  return
                                                              }
                                                          }
                                                          // Fallback to original behavior if load failed
                                                          duplicateInsight(insight as QueryBasedInsightModel, true)
                                                      })()
                                                  },
                                              },
                                          ]
                                        : []),
                                ],
                            },
                            {
                                title: 'Edit',
                                id: 'edit',
                                children: [
                                    ...(insightMode !== ItemMode.Edit && canEditInsight
                                        ? [
                                              {
                                                  title: 'Edit insight',
                                                  id: 'edit-insight',
                                                  icon: dashboardOverridesExist ? <IconWarning /> : <IconPencil />,
                                                  type: 'link' as SceneHeaderItemType,
                                                  onClick: () => {
                                                      if (isDataVisualizationNode(query) && insight.short_id) {
                                                          router.actions.push(
                                                              urls.sqlEditor(undefined, undefined, insight.short_id)
                                                          )
                                                      } else if (insight.short_id) {
                                                          push(urls.insightEdit(insight.short_id))
                                                      } else {
                                                          setInsightMode(ItemMode.Edit, null)
                                                      }
                                                  },
                                                  accessControl: {
                                                      userAccessLevel: insight.user_access_level,
                                                      minAccessLevel: AccessControlLevel.Editor,
                                                      resourceType: AccessControlResourceType.Insight,
                                                  },
                                              },
                                          ]
                                        : [
                                              {
                                                  title:
                                                      !!insight.dashboards?.length && !insight.id
                                                          ? 'Save, add to dashboard'
                                                          : 'Save',
                                                  id: 'save-insight',
                                                  icon: (
                                                      <svg
                                                          className="LemonIcon"
                                                          width="24"
                                                          height="24"
                                                          viewBox="0 0 24 24"
                                                          fill="none"
                                                          xmlns="http://www.w3.org/2000/svg"
                                                      >
                                                          <path
                                                              fillRule="evenodd"
                                                              clipRule="evenodd"
                                                              d="M4.75 4.5C4.61193 4.5 4.5 4.61193 4.5 4.75V19.25C4.5 19.3881 4.61193 19.5 4.75 19.5H7.01772C7.00604 19.4184 7 19.3349 7 19.25V13.75C7 12.7835 7.7835 12 8.75 12H15.25C16.2165 12 17 12.7835 17 13.75V19.25C17 19.3349 16.994 19.4184 16.9823 19.5H19.25C19.3881 19.5 19.5 19.3881 19.5 19.25V7.16421C19.5 7.09791 19.4737 7.03432 19.4268 6.98744L17.0126 4.57322C17.0085 4.56916 17.0043 4.56525 17 4.56149V7.25C17 8.2165 16.2165 9 15.25 9H8.75C7.7835 9 7 8.2165 7 7.25V4.5H4.75ZM4.75 3C3.7835 3 3 3.7835 3 4.75V19.25C3 20.2165 3.7835 21 4.75 21H19.25C20.2165 21 21 20.2165 21 19.25V7.16421C21 6.70009 20.8156 6.25497 20.4874 5.92678L18.0732 3.51256C17.745 3.18437 17.2999 3 16.8358 3H4.75ZM8.5 4.5V7.25C8.5 7.38807 8.61193 7.5 8.75 7.5H15.25C15.3881 7.5 15.5 7.38807 15.5 7.25V4.5H8.5ZM15.25 19.5C15.3881 19.5 15.5 19.3881 15.5 19.25V13.75C15.5 13.6119 15.3881 13.5 15.25 13.5H8.75C8.61193 13.5 8.5 13.6119 8.5 13.75V19.25C8.5 19.3881 8.61193 19.5 8.75 19.5H15.25Z"
                                                              fill="currentColor"
                                                          />
                                                      </svg>
                                                  ),
                                                  type: 'link' as SceneHeaderItemType,
                                                  onClick: () => {
                                                      setInsightMode(ItemMode.Edit, null)
                                                  },
                                                  buttonProps: {
                                                      loading: insightSaving,
                                                      disabled: hasDashboardItemId && !insightChanged,
                                                  },
                                              },
                                              {
                                                  title: 'Save as...',
                                                  id: 'save-as',
                                                  icon: (
                                                      <svg
                                                          className="LemonIcon"
                                                          width="24"
                                                          height="24"
                                                          viewBox="0 0 24 24"
                                                          fill="none"
                                                          xmlns="http://www.w3.org/2000/svg"
                                                      >
                                                          <path
                                                              fillRule="evenodd"
                                                              clipRule="evenodd"
                                                              d="M4.75 4.5C4.61193 4.5 4.5 4.61193 4.5 4.75V19.25C4.5 19.3881 4.61193 19.5 4.75 19.5H7.01772C7.00604 19.4184 7 19.3349 7 19.25V13.75C7 12.7835 7.7835 12 8.75 12H15.25C16.2165 12 17 12.7835 17 13.75V19.25C17 19.3349 16.994 19.4184 16.9823 19.5H19.25C19.3881 19.5 19.5 19.3881 19.5 19.25V7.16421C19.5 7.09791 19.4737 7.03432 19.4268 6.98744L17.0126 4.57322C17.0085 4.56916 17.0043 4.56525 17 4.56149V7.25C17 8.2165 16.2165 9 15.25 9H8.75C7.7835 9 7 8.2165 7 7.25V4.5H4.75ZM4.75 3C3.7835 3 3 3.7835 3 4.75V19.25C3 20.2165 3.7835 21 4.75 21H19.25C20.2165 21 21 20.2165 21 19.25V7.16421C21 6.70009 20.8156 6.25497 20.4874 5.92678L18.0732 3.51256C17.745 3.18437 17.2999 3 16.8358 3H4.75ZM8.5 4.5V7.25C8.5 7.38807 8.61193 7.5 8.75 7.5H15.25C15.3881 7.5 15.5 7.38807 15.5 7.25V4.5H8.5ZM15.25 19.5C15.3881 19.5 15.5 19.3881 15.5 19.25V13.75C15.5 13.6119 15.3881 13.5 15.25 13.5H8.75C8.61193 13.5 8.5 13.6119 8.5 13.75V19.25C8.5 19.3881 8.61193 19.5 8.75 19.5H15.25Z"
                                                              fill="currentColor"
                                                          />
                                                      </svg>
                                                  ),
                                                  type: 'link' as SceneHeaderItemType,
                                                  onClick: () => {
                                                      openSaveToModal({
                                                          callback: (folder) => saveAs(undefined, undefined, folder),
                                                          defaultFolder: 'Unfiled/Insights',
                                                      })
                                                  },
                                                  buttonProps: {
                                                      loading: insightSaving,
                                                      disabled: hasDashboardItemId && !insightChanged,
                                                  },
                                              },
                                              {
                                                  title: 'Cancel changes',
                                                  id: 'cancel-change',
                                                  icon: <IconX />,
                                                  type: 'link' as SceneHeaderItemType,
                                                  onClick: () => {
                                                      setInsightMode(ItemMode.View, null)
                                                  },
                                              },
                                          ]),
                                ],
                            },
                        ]}
                    >
                        {insightMode === ItemMode.Edit && hasDashboardItemId && (
                            <LemonButton
                                type="secondary"
                                onClick={() => setInsightMode(ItemMode.View, null)}
                                data-attr="insight-cancel-edit-button"
                            >
                                Cancel
                            </LemonButton>
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
                                saveAs={() =>
                                    openSaveToModal({
                                        callback: (folder) => saveAs(undefined, undefined, folder),
                                        defaultFolder: 'Unfiled/Insights',
                                    })
                                }
                                saveInsight={(redirectToViewMode) =>
                                    insight.short_id
                                        ? saveInsight(redirectToViewMode)
                                        : openSaveToModal({
                                              callback: (folder) => saveInsight(redirectToViewMode, folder),
                                              defaultFolder: 'Unfiled/Insights',
                                          })
                                }
                                isSaved={hasDashboardItemId}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged || queryChanged}
                            />
                        )}
                    </SceneHeader>
                }
            >
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

                            {insightMode !== ItemMode.Edit && hasDashboardItemId && (
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
                                                router.actions.push(
                                                    urls.sqlEditor(undefined, undefined, insight.short_id)
                                                )
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
                                    saveAs={() =>
                                        openSaveToModal({
                                            callback: (folder) => saveAs(undefined, undefined, folder),
                                            defaultFolder: 'Unfiled/Insights',
                                        })
                                    }
                                    saveInsight={(redirectToViewMode) =>
                                        insight.short_id
                                            ? saveInsight(redirectToViewMode)
                                            : openSaveToModal({
                                                  callback: (folder) => saveInsight(redirectToViewMode, folder),
                                                  defaultFolder: 'Unfiled/Insights',
                                              })
                                    }
                                    isSaved={hasDashboardItemId}
                                    addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                    insightSaving={insightSaving}
                                    insightChanged={insightChanged || queryChanged}
                                />
                            )}

                            <More
                                overlay={
                                    <>
                                        {hasDashboardItemId && (
                                            <>
                                                <LemonButton
                                                    onClick={() => {
                                                        void (async () => {
                                                            // We do not want to duplicate the dashboard filters that might be included in this insight
                                                            // Ideally we would store those separately and be able to remove them on duplicate or edit, but current we merge them
                                                            // irreversibly in apply_dashboard_filters and return that to the front-end
                                                            if (insight.short_id) {
                                                                const cleanInsight = await insightsApi.getByShortId(
                                                                    insight.short_id
                                                                )
                                                                if (cleanInsight) {
                                                                    duplicateInsight(cleanInsight, true)
                                                                    return
                                                                }
                                                            }
                                                            // Fallback to original behavior if load failed
                                                            duplicateInsight(insight as QueryBasedInsightModel, true)
                                                        })()
                                                    }}
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
                                                                loadInsights()
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
                        </div>
                    }
                    caption={
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
                    }
                    tabbedPage={insightMode === ItemMode.Edit} // Insight type tabs are only shown in edit mode
                />
            </SceneLayout>
        </>
    )
}
