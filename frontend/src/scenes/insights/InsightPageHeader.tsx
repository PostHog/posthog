import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { AlertsButton, AlertsModal } from 'lib/components/Alerts/AlertsModal'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { useState } from 'react'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { tagsModel } from '~/models/tagsModel'
import { DataTableNode, NodeKind } from '~/queries/schema'
import {
    ExporterFormat,
    InsightLogicProps,
    InsightShortId,
    ItemMode,
    NotebookNodeType,
    QueryBasedInsightModel,
} from '~/types'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    // insightSceneLogic
    const { insightMode, itemId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const { insightProps, canEditInsight, insight, insightChanged, insightSaving, hasDashboardItemId } = useValues(
        insightLogic(insightLogicProps)
    )
    const { setInsightMetadata, saveAs, saveInsight } = useActions(insightLogic(insightLogicProps))

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

    // insightDataLogic
    const { queryChanged, showQueryEditor, showDebugPanel, hogQL, exportContext } = useValues(
        insightDataLogic(insightProps)
    )
    const { toggleQueryEditorPanel, toggleDebugPanel } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
    const { tags } = useValues(tagsModel)
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)

    const [addToDashboardModalOpen, setAddToDashboardModalOpenModal] = useState<boolean>(false)

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
                    <AlertsModal
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        isOpen={insightMode === ItemMode.Alerts}
                        insightLogicProps={insightLogicProps}
                        insightId={insight.id as number}
                        insightShortId={insight.short_id as InsightShortId}
                        alertId={typeof itemId === 'string' ? itemId : null}
                    />
                    <NewDashboardModal />
                </>
            )}
            <PageHeader
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        <More
                            overlay={
                                <>
                                    {hasDashboardItemId && (
                                        <>
                                            <LemonButton
                                                onClick={() =>
                                                    duplicateInsight(insight as QueryBasedInsightModel, true)
                                                }
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
                                            <AlertsButton insight={insight} />
                                            <LemonDivider />
                                        </>
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
                                    {hogQL && (
                                        <>
                                            <LemonDivider />
                                            <LemonButton
                                                data-attr="edit-insight-sql"
                                                onClick={() => {
                                                    router.actions.push(
                                                        urls.insightNew(undefined, undefined, {
                                                            kind: NodeKind.DataTableNode,
                                                            source: {
                                                                kind: NodeKind.HogQLQuery,
                                                                query: hogQL,
                                                            },
                                                            full: true,
                                                        } as DataTableNode)
                                                    )
                                                }}
                                                fullWidth
                                            >
                                                Edit SQL directly
                                            </LemonButton>
                                            <LemonButton
                                                data-attr="edit-insight-sql"
                                                onClick={() => {
                                                    LemonDialog.openForm({
                                                        title: 'Save as static cohort',
                                                        description:
                                                            'Your query must export one actor_id column, which must match the id column on the persons table',
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
                                                            try {
                                                                const cohort = await api.create('api/cohort', {
                                                                    is_static: true,
                                                                    name: name || 'Query cohort',
                                                                    query: { kind: NodeKind.HogQLQuery, query: hogQL },
                                                                })
                                                                cohortsModel.actions.cohortCreated(cohort)
                                                                lemonToast.success('Cohort saved', {
                                                                    toastId: `cohort-saved-${cohort.id}`,
                                                                    button: {
                                                                        label: 'View cohort',
                                                                        action: () =>
                                                                            router.actions.push(urls.cohort(cohort.id)),
                                                                    },
                                                                })
                                                            } catch (e) {
                                                                lemonToast.error('Cohort save failed')
                                                            }
                                                        },
                                                    })
                                                }}
                                                fullWidth
                                            >
                                                Save as static cohort
                                            </LemonButton>
                                        </>
                                    )}
                                    {hasDashboardItemId && (
                                        <>
                                            <LemonDivider />
                                            <LemonButton
                                                status="danger"
                                                onClick={() =>
                                                    void deleteInsightWithUndo({
                                                        object: insight as QueryBasedInsightModel,
                                                        endpoint: `projects/${currentTeamId}/insights`,
                                                        callback: () => {
                                                            loadInsights()
                                                            push(urls.savedInsights())
                                                        },
                                                    })
                                                }
                                                fullWidth
                                            >
                                                Delete insight
                                            </LemonButton>
                                        </>
                                    )}
                                </>
                            }
                        />
                        <LemonDivider vertical />

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
                                <LemonButton
                                    type="primary"
                                    onClick={() => setInsightMode(ItemMode.Edit, null)}
                                    data-attr="insight-edit-button"
                                >
                                    Edit
                                </LemonButton>
                            )
                        ) : (
                            <InsightSaveButton
                                saveAs={saveAs}
                                saveInsight={saveInsight}
                                isSaved={hasDashboardItemId}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged || queryChanged}
                            />
                        )}
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
                                tags={insight.tags ?? []}
                                saving={insightSaving}
                                onChange={(tags) => setInsightMetadata({ tags: tags ?? [] })}
                                tagsAvailable={tags}
                                className="mt-2"
                                data-attr="insight-tags"
                            />
                        ) : insight.tags?.length ? (
                            <ObjectTags
                                tags={insight.tags}
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
