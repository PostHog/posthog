import { EditableField } from 'lib/components/EditableField/EditableField'
import { summariseInsight } from 'scenes/insights/utils'
import { IconLock } from 'lib/lemon-ui/icons'
import { AvailableFeature, ExporterFormat, InsightLogicProps, InsightModel, InsightShortId, ItemMode } from '~/types'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { urls } from 'scenes/urls'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { deleteWithUndo } from 'lib/utils'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { isInsightVizNode } from '~/queries/utils'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { PageHeader } from 'lib/components/PageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { userLogic } from 'scenes/userLogic'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { tagsModel } from '~/models/tagsModel'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { Tooltip } from 'antd'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    // insightSceneLogic
    const { insightMode, subscriptionId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const logic = insightLogic(insightLogicProps)
    const {
        insightProps,
        filters,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        exporterResourceParams,
        isUsingDataExploration,
        isFilterBasedInsight,
        isQueryBasedInsight,
        displayRefreshButtonChangedNotice,
        insightRefreshButtonDisabledReason,
    } = useValues(logic)
    const { saveInsight, setInsightMetadata, saveAs, loadResults, acknowledgeRefreshButtonChanged } = useActions(logic)

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

    // insightDataLogic
    const { query: insightVizQuery } = useValues(insightDataLogic(insightProps))
    const { setQuery: insightVizSetQuery, saveInsight: saveQueryBasedInsight } = useActions(
        insightDataLogic(insightProps)
    )

    // TODO - separate presentation of insight with viz query from insight with query
    let query = insightVizQuery
    let setQuery = insightVizSetQuery
    if (!!insight.query && isQueryBasedInsight) {
        query = insight.query
        setQuery = () => {
            // don't support editing non-insight viz queries _yet_
        }
    }

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)
    const { tags } = useValues(tagsModel)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)

    const saveInsightHandler = isUsingDataExploration ? saveQueryBasedInsight : saveInsight

    return (
        <>
            {insight.short_id !== 'new' && (
                <>
                    <SubscriptionsModal
                        isOpen={insightMode === ItemMode.Subscriptions}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        subscriptionId={subscriptionId}
                    />

                    <SharingModal
                        isOpen={insightMode === ItemMode.Sharing}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        insight={insight}
                    />
                </>
            )}
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={insight.name || ''}
                        placeholder={summariseInsight(
                            isUsingDataExploration,
                            query,
                            aggregationLabel,
                            cohortsById,
                            mathDefinitions,
                            filters
                        )}
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
                        {insightMode === ItemMode.Edit ? (
                            <>
                                <Tooltip
                                    title={
                                        displayRefreshButtonChangedNotice ? `The 'Refresh' button has moved here.` : ''
                                    }
                                    visible={displayRefreshButtonChangedNotice}
                                    zIndex={940}
                                >
                                    <More
                                        onClick={
                                            displayRefreshButtonChangedNotice
                                                ? acknowledgeRefreshButtonChanged
                                                : undefined
                                        }
                                        overlay={
                                            <>
                                                <LemonButton
                                                    status="stealth"
                                                    onClick={() => loadResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-insight-from-insight-view"
                                                    disabledReason={insightRefreshButtonDisabledReason}
                                                >
                                                    Refresh
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                </Tooltip>
                                <LemonDivider vertical />
                            </>
                        ) : null}
                        {insightMode !== ItemMode.Edit && (
                            <>
                                <Tooltip
                                    title={
                                        displayRefreshButtonChangedNotice ? `The 'Refresh' button has moved here.` : ''
                                    }
                                    visible={displayRefreshButtonChangedNotice}
                                >
                                    <More
                                        onClick={
                                            displayRefreshButtonChangedNotice
                                                ? acknowledgeRefreshButtonChanged
                                                : undefined
                                        }
                                        overlay={
                                            <>
                                                <LemonButton
                                                    status="stealth"
                                                    onClick={() => loadResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-insight-from-insight-view"
                                                    disabledReason={insightRefreshButtonDisabledReason}
                                                >
                                                    Refresh
                                                </LemonButton>
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
                                </Tooltip>
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
                            canEditInsight &&
                            (isFilterBasedInsight || isInsightVizNode(query)) && (
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
                                saveInsight={saveInsightHandler}
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
