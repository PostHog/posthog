import { EditableField } from 'lib/components/EditableField/EditableField'
import { IconLock } from 'lib/lemon-ui/icons'
import { AvailableFeature, ExporterFormat, InsightModel, InsightShortId, ItemMode } from '~/types'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { urls } from 'scenes/urls'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { deleteWithUndo } from 'lib/utils'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { PageHeader } from 'lib/components/PageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { userLogic } from 'scenes/userLogic'
import { tagsModel } from '~/models/tagsModel'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useMountedLogic, useValues } from 'kea'
import { InsightSceneProps } from 'scenes/insights/Insight'
import { router } from 'kea-router'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { insightSummaryString } from 'lib/components/InsightSummary'
import { insightQueryLogic } from 'scenes/insights/insightQueryLogic'

export function InsightPageHeader({ insightId }: InsightSceneProps): JSX.Element {
    // insightSceneLogic
    const { insightMode, subscriptionId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const logic = insightLogic({ dashboardItemId: insightId || 'new' })
    const {
        insightProps,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        exporterResourceParams,
        isUsingDataExploration,
    } = useValues(logic)
    const { saveInsight, setInsightMetadata, saveAs } = useActions(logic)

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

    const { query } = useValues(insightQueryLogic(insightProps))
    const { setQuery } = useActions(insightQueryLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)
    const { tags } = useValues(tagsModel)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)

    return (
        <>
            {insightId !== 'new' && (
                <>
                    <SubscriptionsModal
                        isOpen={insightMode === ItemMode.Subscriptions}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insightId}
                        subscriptionId={subscriptionId}
                    />

                    <SharingModal
                        isOpen={insightMode === ItemMode.Sharing}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insightId}
                        insight={insight}
                    />
                </>
            )}
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={insight.name || ''}
                        placeholder={insightSummaryString({
                            insight: { name: insight.name, filters: insight.filters, query } as Partial<InsightModel>,
                            isUsingDataExploration,
                        })}
                        onSave={(value) => setInsightMetadata({ name: value })}
                        saveOnBlur={true}
                        maxLength={400} // Sync with Insight model
                        mode={!canEditInsight ? 'view' : undefined}
                        data-attr="insight-name"
                        notice={
                            !canEditInsight
                                ? {
                                      icon: <IconLock />,
                                      tooltip:
                                          "You don't have edit permissions on any of the dashboards this insight belongs to. Ask a dashboard collaborator with edit access to add you.",
                                  }
                                : undefined
                        }
                    />
                }
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        {insightMode !== ItemMode.Edit && (
                            <>
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                status="stealth"
                                                onClick={() => duplicateInsight(insight as InsightModel, true)}
                                                fullWidth
                                                data-attr="duplicate-insight-from-insight-view"
                                            >
                                                Duplicate
                                            </LemonButton>
                                            <LemonButton
                                                status="stealth"
                                                onClick={() =>
                                                    setInsightMetadata({
                                                        favorited: !insight.favorited,
                                                    })
                                                }
                                                fullWidth
                                            >
                                                {insight.favorited ? 'Remove from favorites' : 'Add to favorites'}
                                            </LemonButton>
                                            <LemonDivider />

                                            <LemonButton
                                                status="stealth"
                                                onClick={() =>
                                                    insight.short_id
                                                        ? push(urls.insightSharing(insight.short_id))
                                                        : null
                                                }
                                                fullWidth
                                            >
                                                Share or embed
                                            </LemonButton>
                                            {insight.short_id && (
                                                <>
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

                                            <LemonButton
                                                status="danger"
                                                onClick={() =>
                                                    deleteWithUndo({
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
                                    }
                                />
                                <LemonDivider vertical />
                            </>
                        )}
                        {insightMode === ItemMode.Edit && insight.saved && (
                            <LemonButton type="secondary" onClick={() => setInsightMode(ItemMode.View, null)}>
                                Cancel
                            </LemonButton>
                        )}
                        {insightMode !== ItemMode.Edit && insight.short_id && (
                            <AddToDashboard insight={insight} canEditInsight={canEditInsight} />
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
                                isSaved={insight.saved}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged}
                            />
                        )}
                        {isUsingDataExploration && <InlineEditorButton query={query} setQuery={setQuery} />}
                    </div>
                }
                caption={
                    <>
                        {!!(canEditInsight || insight.description) && (
                            <EditableField
                                multiline
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
                                className="insight-metadata-tags"
                                data-attr="insight-tags"
                            />
                        ) : insight.tags?.length ? (
                            <ObjectTags
                                tags={insight.tags}
                                saving={insightSaving}
                                className="insight-metadata-tags"
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
