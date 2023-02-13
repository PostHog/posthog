import './Insight.scss'
import { useEffect } from 'react'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from './insightLogic'
import { insightCommandLogic } from './insightCommandLogic'
import { insightDataLogic } from './insightDataLogic'
import { AvailableFeature, ExporterFormat, InsightModel, InsightShortId, InsightType, ItemMode } from '~/types'
import { InsightsNav } from './InsightsNav'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { InsightSaveButton } from './InsightSaveButton'
import { userLogic } from 'scenes/userLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { IconLock } from 'lib/lemon-ui/icons'
import { summarizeInsightFilters, summarizeInsightQuery } from './utils'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { EditorFilters } from './EditorFilters/EditorFilters'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import clsx from 'clsx'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { tagsModel } from '~/models/tagsModel'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode } from '~/queries/schema'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'
import { isInsightVizNode } from '~/queries/utils'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { insightQueryEditorLogic } from './insightQueryEditorLogic'

export function Insight({ insightId }: { insightId: InsightShortId | 'new' }): JSX.Element {
    // insightSceneLogic
    const { insightMode, subscriptionId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const logic = insightLogic({ dashboardItemId: insightId || 'new' })
    const {
        insightProps,
        insightLoading,
        filtersKnown,
        filters,
        canEditInsight,
        insight,
        insightChanged,
        tagLoading,
        insightSaving,
        exporterResourceParams,
        isUsingDataExploration,
        isUsingQueryBasedInsights,
        erroredQueryId,
        isFilterBasedInsight,
        isQueryBasedInsight,
        isInsightVizQuery,
        activeView,
    } = useValues(logic)
    const {
        saveInsight,
        setInsightMetadata,
        saveAs,
        reportInsightViewedForRecentInsights,
        abortAnyRunningQuery,
        loadResults,
    } = useActions(logic)

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

    // insightDataLogic
    const { query: insightVizQuery } = useValues(insightDataLogic(insightProps))
    const { setQuery: insightVizSetQuery } = useActions(insightDataLogic(insightProps))

    const { query: insightEditorQuery } = useValues(
        insightQueryEditorLogic({ ...insightProps, query: insightVizQuery })
    )
    const { setQuery: insightEditorSetQuery } = useActions(
        insightQueryEditorLogic({ ...insightProps, query: insightVizQuery })
    )
    // TODO - separate presentation of insight with viz query from insight with query
    let query = insightVizQuery
    let setQuery = insightVizSetQuery
    if (!!insightEditorQuery && isQueryBasedInsight) {
        query = insightEditorQuery
        setQuery = insightEditorSetQuery
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

    useEffect(() => {
        reportInsightViewedForRecentInsights()
    }, [insightId])

    useEffect(() => {
        // if users navigate away from insights then we may cancel an API call
        // and when they come back they may see an error state, so clear it
        if (!!erroredQueryId) {
            loadResults()
        }
        return () => {
            // request cancellation of any running queries when this component is no longer in the dom
            abortAnyRunningQuery()
        }
    }, [])
    // if this is a non-viz query-based insight e.g. an events table then don't show the insight editing chrome
    const showFilterEditing = activeView !== InsightType.QUERY && isFilterBasedInsight

    // Show the skeleton if loading an insight for which we only know the id
    // This helps with the UX flickering and showing placeholder "name" text.
    if (insightId !== 'new' && insightLoading && !filtersKnown) {
        return <InsightSkeleton />
    }

    const insightScene = (
        <div className={'insights-page'}>
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
                        placeholder={
                            isUsingDataExploration && isInsightVizQuery
                                ? summarizeInsightQuery(
                                      (query as InsightVizNode).source,
                                      aggregationLabel,
                                      cohortsById,
                                      mathDefinitions
                                  )
                                : isFilterBasedInsight
                                ? summarizeInsightFilters(filters, aggregationLabel, cohortsById, mathDefinitions)
                                : 'Custom query'
                        }
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
                                onChange={(_, tags) => setInsightMetadata({ tags: tags ?? [] })}
                                saving={tagLoading}
                                tagsAvailable={tags}
                                className="insight-metadata-tags"
                                data-attr="insight-tags"
                            />
                        ) : insight.tags?.length ? (
                            <ObjectTags
                                tags={insight.tags}
                                saving={tagLoading}
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
            />

            {insightMode === ItemMode.Edit && <InsightsNav />}

            {isUsingDataExploration || (isUsingQueryBasedInsights && isQueryBasedInsight) ? (
                <>
                    {insightMode === ItemMode.Edit && isQueryBasedInsight && (
                        <>
                            <QueryEditor
                                query={JSON.stringify(query, null, 4)}
                                setQuery={setQuery ? (query) => setQuery(JSON.parse(query)) : undefined}
                            />
                        </>
                    )}
                    <Query query={query} setQuery={setQuery} />
                </>
            ) : (
                <>
                    <div
                        className={clsx('insight-wrapper', {
                            'insight-wrapper--singlecolumn': filters.insight === InsightType.FUNNELS,
                        })}
                    >
                        {showFilterEditing && (
                            <EditorFilters insightProps={insightProps} showing={insightMode === ItemMode.Edit} />
                        )}
                        <div className="insights-container" data-attr="insight-view">
                            <InsightContainer insightMode={insightMode} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            {insightScene}
        </BindLogic>
    )
}
