import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { useState } from 'react'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'
import { DataTableNode, NodeKind } from '~/queries/schema'
import {
    AvailableFeature,
    ExporterFormat,
    InsightLogicProps,
    InsightModel,
    InsightShortId,
    ItemMode,
    NotebookNodeType,
} from '~/types'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    // insightSceneLogic
    const { insightMode, subscriptionId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const logic = insightLogic(insightLogicProps)
    const {
        insightProps,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        hasDashboardItemId,
        exporterResourceParams,
    } = useValues(logic)
    const { setInsightMetadata } = useActions(logic)

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

    // insightDataLogic
    const { queryChanged, showQueryEditor, hogQL } = useValues(insightDataLogic(insightProps))
    const { saveInsight, saveAs, toggleQueryEditorPanel } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)
    const { tags } = useValues(tagsModel)
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
                        subscriptionId={subscriptionId}
                    />
                    <SharingModal
                        title="Insight Sharing"
                        isOpen={insightMode === ItemMode.Sharing}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        insight={insight}
                        previewIframe
                    />
                    <AddToDashboardModal
                        isOpen={addToDashboardModalOpen}
                        closeModal={() => setAddToDashboardModalOpenModal(false)}
                        insight={insight}
                        canEditInsight={canEditInsight}
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
                                                onClick={() => duplicateInsight(insight as InsightModel, true)}
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
                                            {exporterResourceParams ? (
                                                <ExportButton
                                                    fullWidth
                                                    items={[
                                                        {
                                                            export_format: ExporterFormat.PNG,
                                                            insight: insight.id,
                                                        },
                                                        {
                                                            export_format: ExporterFormat.CSV,
                                                            export_context: exporterResourceParams,
                                                        },
                                                    ]}
                                                />
                                            ) : null}
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
                                        label="View Source"
                                    />
                                    {hogQL && (
                                        <>
                                            <LemonDivider />
                                            <LemonButton
                                                data-attr="edit-insight-sql"
                                                onClick={() => {
                                                    router.actions.push(
                                                        urls.insightNew(
                                                            undefined,
                                                            undefined,
                                                            JSON.stringify({
                                                                kind: NodeKind.DataTableNode,
                                                                source: {
                                                                    kind: NodeKind.HogQLQuery,
                                                                    query: hogQL,
                                                                },
                                                                full: true,
                                                            } as DataTableNode)
                                                        )
                                                    )
                                                }}
                                                fullWidth
                                            >
                                                Edit SQL directly
                                            </LemonButton>
                                        </>
                                    )}
                                    {hasDashboardItemId && (
                                        <>
                                            <LemonDivider />
                                            <LemonButton
                                                status="danger"
                                                onClick={() =>
                                                    void deleteWithUndo({
                                                        object: insight,
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
                            <LemonButton type="secondary" onClick={() => setInsightMode(ItemMode.View, null)}>
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
                                paywall={!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)}
                            />
                        )}
                        {canEditInsight ? (
                            <ObjectTags
                                tags={insight.tags ?? []}
                                saving={insightSaving}
                                onChange={(_, tags) => setInsightMetadata({ tags: tags ?? [] })}
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
