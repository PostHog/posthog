import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { removeUndefinedAndNull } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { DataVisualizationNode, FileSystemIconType, HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import type { editorSceneLogicType } from './editorSceneLogicType'
import {
    getCurrentVisualizationQuery,
    normalizeFiltersForUrl,
    sqlEditorLogic,
    toDataVisualizationNode,
} from './sqlEditorLogic'

export interface SaveAsMenuItem {
    action: 'insight' | 'endpoint' | 'view'
    label: string
    dataAttr?: string
}

function setFiltersHashParam(url: URL, filters: HogQLFilters | null | undefined): void {
    const normalizedFilters = normalizeFiltersForUrl(filters)
    if (!normalizedFilters) {
        return
    }

    const hashParams = new URLSearchParams(url.hash ? url.hash.slice(1) : '')
    hashParams.set('filters', JSON.stringify(normalizedFilters))
    url.hash = hashParams.toString()
}

export const renderTableCount = (count: undefined | number): null | JSX.Element => {
    if (!count) {
        return null
    }

    return (
        <span className="text-xs mr-1 italic text-[color:var(--color-text-secondary-3000)]">
            {`(${new Intl.NumberFormat('en', {
                notation: 'compact',
                compactDisplay: 'short',
            })
                .format(count)
                .toLowerCase()})`}
        </span>
    )
}

export interface EditorSceneLogicProps {
    tabId: string
}

export const editorSceneLogic = kea<editorSceneLogicType>([
    path(['data-warehouse', 'editor', 'editorSceneLogic']),
    props({} as EditorSceneLogicProps),
    tabAwareScene(),
    connect((props: EditorSceneLogicProps) => ({
        values: [
            sqlEditorLogic({ tabId: props.tabId }),
            [
                'activeTab',
                'dashboardId',
                'dataLogicKey',
                'editingInsight',
                'editingView',
                'editorSource',
                'featureFlags',
                'insightLoading',
                'queryInput',
                'sourceQuery',
                'viewLoading',
            ],
        ],
    })),
    actions({
        shareTab: true,
        openHistoryModal: true,
        closeHistoryModal: true,
    }),
    reducers({
        isHistoryModalOpen: [
            false as boolean,
            {
                openHistoryModal: () => true,
                closeHistoryModal: () => false,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.activeTab],
            (activeTab): Breadcrumb[] => {
                const { draft, insight, view } = activeTab || {}
                const first = {
                    key: Scene.SQLEditor,
                    name: 'SQL query',
                    to: urls.sqlEditor(),
                    iconType: 'sql_editor' as FileSystemIconType,
                }
                if (view) {
                    return [
                        {
                            key: view.id,
                            name: view.name,
                            path: urls.sqlEditor({ view_id: view.id }),
                            iconType: 'sql_editor',
                        },
                    ]
                } else if (insight) {
                    return [
                        first,
                        {
                            key: insight.id,
                            name: insight.name || insight.derived_name || 'Untitled',
                            path: urls.sqlEditor({
                                insightShortId: insight.short_id,
                            }),
                            iconType: 'sql_editor',
                        },
                    ]
                } else if (draft) {
                    return [
                        first,
                        {
                            key: draft.id,
                            name: draft.name || 'Untitled',
                            path: urls.sqlEditor({ draftId: draft.id }),
                            iconType: 'sql_editor',
                        },
                    ]
                }
                return [first]
            },
        ],
        titleSectionProps: [
            (s) => [
                s.editingInsight,
                s.insightLoading,
                s.editingView,
                s.viewLoading,
                s.editorSource,
                s.dashboardId,
                s.activeTab,
            ],
            (editingInsight, insightLoading, editingView, viewLoading, editorSource, dashboardId, activeTab) => {
                if (editingInsight) {
                    const forceBackTo: Breadcrumb = dashboardId
                        ? {
                              key: 'dashboard',
                              name: 'Back to dashboard',
                              path: urls.dashboard(dashboardId),
                              iconType: 'dashboard',
                          }
                        : {
                              key: editingInsight.short_id,
                              name: 'Back to insight',
                              path: urls.insightView(editingInsight.short_id),
                              iconType: 'insight/hog',
                          }

                    return {
                        forceBackTo,
                        name: editingInsight.name || editingInsight.derived_name || 'Untitled',
                        resourceType: { type: 'insight/hog' },
                    }
                }

                if (insightLoading) {
                    return {
                        name: 'Loading insight...',
                        resourceType: { type: 'insight/hog' },
                    }
                }

                if (editingView) {
                    return {
                        name: editingView.name,
                        resourceType: {
                            type: editingView.is_materialized ? 'matview' : 'view',
                        },
                    }
                }

                if (viewLoading) {
                    return {
                        name: 'Loading view...',
                        resourceType: { type: 'view' },
                    }
                }

                if (!activeTab) {
                    const searchParams = new URLSearchParams(window.location.search)
                    const hashParams = new URLSearchParams(window.location.hash.slice(1))
                    if (searchParams.get('open_view') || hashParams.get('view')) {
                        return {
                            name: 'Loading view...',
                            resourceType: { type: 'view' },
                        }
                    }

                    if (searchParams.get('open_insight') || hashParams.get('insight')) {
                        return {
                            name: 'Loading insight...',
                            resourceType: { type: 'insight/hog' },
                        }
                    }
                }

                if (editorSource === 'endpoint') {
                    const forceBackTo: Breadcrumb = {
                        key: 'endpoints',
                        name: 'Endpoints',
                        path: urls.endpoints(),
                        iconType: 'endpoints',
                    }

                    return {
                        forceBackTo,
                        name: 'New endpoint',
                        resourceType: { type: 'sql_editor' },
                    }
                }

                if (dashboardId) {
                    const forceBackTo: Breadcrumb = {
                        key: 'dashboard',
                        name: 'Back to dashboard',
                        path: urls.dashboard(dashboardId),
                        iconType: 'dashboard',
                    }

                    return {
                        forceBackTo,
                        name: 'New SQL query',
                        resourceType: { type: 'sql_editor' },
                    }
                }

                return {
                    name: 'New SQL query',
                    resourceType: { type: 'sql_editor' },
                }
            },
        ],
        saveAsMenuItems: [
            (s) => [s.editorSource, s.dashboardId, s.featureFlags],
            (editorSource, dashboardId, featureFlags): { primary: SaveAsMenuItem; secondary: SaveAsMenuItem[] } => {
                const endpointsEnabled = !!featureFlags[FEATURE_FLAGS.ENDPOINTS]
                const saveAsInsightItem: SaveAsMenuItem = {
                    action: 'insight',
                    label: dashboardId ? 'Save & add to dashboard' : 'Save as insight',
                }
                const saveAsEndpointItem: SaveAsMenuItem = {
                    action: 'endpoint',
                    label: 'Save as endpoint',
                }
                const saveAsViewItem: SaveAsMenuItem = {
                    action: 'view',
                    label: 'Save as view',
                    dataAttr: 'sql-editor-save-view-button',
                }

                if (editorSource === 'endpoint' && endpointsEnabled) {
                    return {
                        primary: saveAsEndpointItem,
                        secondary: [saveAsInsightItem, saveAsViewItem],
                    }
                }

                return {
                    primary: saveAsInsightItem,
                    secondary: endpointsEnabled ? [saveAsEndpointItem, saveAsViewItem] : [saveAsViewItem],
                }
            },
        ],
        updateInsightButtonEnabled: [
            (s) => [s.sourceQuery, s.activeTab, s.editingInsight, s.dataLogicKey],
            (sourceQuery, activeTab, editingInsight, dataLogicKey) => {
                if (!editingInsight?.query) {
                    return false
                }

                const updatedName = activeTab?.name !== editingInsight.name
                const currentVisualizationQuery = getCurrentVisualizationQuery(dataLogicKey, sourceQuery)

                const sourceQueryWithoutUndefinedAndNullKeys = removeUndefinedAndNull(currentVisualizationQuery)
                // Normalize so DataTableNode-based insights don't look "changed" immediately after load.
                const editingInsightQuery = toDataVisualizationNode(editingInsight.query) ?? editingInsight.query

                return (
                    updatedName ||
                    !equal(sourceQueryWithoutUndefinedAndNullKeys, removeUndefinedAndNull(editingInsightQuery))
                )
            },
        ],
    }),
    listeners(({ values }) => ({
        shareTab: () => {
            const { activeTab, queryInput, sourceQuery } = values
            if (!activeTab) {
                return
            }

            const currentUrl = new URL(window.location.href)
            const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)

            if (activeTab.insight) {
                shareUrl.searchParams.set('open_insight', activeTab.insight.short_id)

                if (activeTab.insight.query?.kind === NodeKind.DataVisualizationNode) {
                    const query = (activeTab.insight.query as DataVisualizationNode).source.query
                    if (queryInput !== query) {
                        shareUrl.searchParams.set('open_query', queryInput ?? '')
                    }
                }
            } else if (activeTab.view) {
                shareUrl.searchParams.set('open_view', activeTab.view.id)

                if (queryInput !== activeTab.view.query?.query) {
                    shareUrl.searchParams.set('open_query', queryInput ?? '')
                }
            } else {
                shareUrl.searchParams.set('open_query', queryInput ?? '')
            }

            setFiltersHashParam(shareUrl, sourceQuery.source.filters)

            void copyToClipboard(shareUrl.toString(), 'share link')
        },
    })),
    selectors({
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                access_control_resource: 'warehouse_objects',
            }),
        ],
    }),
])
