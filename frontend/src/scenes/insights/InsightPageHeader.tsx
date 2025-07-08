import { IconInfo, IconWarning } from '@posthog/icons'
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
                                        : saveInsight(redirectToViewMode, 'Unfiled/Insights')
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
                                                            <code>actor_id</code> or <code>id</code> column, which must
                                                            match the <code>id</code> of the <code>persons</code> table
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
        </>
    )
}
