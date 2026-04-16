import { Monaco } from '@monaco-editor/react'
import {
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import isEqual from 'lodash.isequal'
import { Uri, editor } from 'monaco-editor'
import posthog from 'posthog-js'

import { LemonCheckbox, LemonDialog, LemonInput, LemonSelect, lemonToast, Tooltip } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { initModel } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { objectsEqual, removeUndefinedAndNull, slugify } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { parseQueryTablesAndColumns } from 'scenes/data-warehouse/editor/sql-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { queryExportContext } from '~/queries/query'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    DataVisualizationNode,
    DatabaseSchemaViewTable,
    FileSystemIconType,
    HogQLMetadataResponse,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    ChartDisplayType,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDraft,
    ExportContext,
    ExternalDataSource,
    LineageGraph,
    QueryBasedInsightModel,
} from '~/types'

import { DagSelector, openCreateDagDialog } from 'products/data_modeling/frontend/DagSelector'
import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import { validateEndpointName } from 'products/endpoints/frontend/common'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { dataModelingLogic } from '../scene/dataModelingLogic'
import { draftsLogic } from './draftsLogic'
import { editorSceneLogic } from './editorSceneLogic'
import { fixSQLErrorsLogic } from './fixSQLErrorsLogic'
import { OutputTab, outputPaneLogic } from './outputPaneLogic'
import type { sqlEditorLogicType } from './sqlEditorLogicType'
import { SQLEditorMode, isEmbeddedSQLEditorMode } from './sqlEditorModes'
import {
    aiSuggestionOnAccept,
    aiSuggestionOnAcceptText,
    aiSuggestionOnReject,
    aiSuggestionOnRejectText,
} from './suggestions/aiSuggestion'
import { ViewEmptyState } from './ViewLoadingState'

export interface SqlEditorLogicProps {
    tabId: string
    mode?: SQLEditorMode
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

export const NEW_QUERY = 'Untitled'

export interface QueryTab {
    uri: Uri
    view?: DataWarehouseSavedQuery
    name: string
    sourceQuery?: DataVisualizationNode
    insight?: QueryBasedInsightModel
    response?: Record<string, any>
    draft?: DataWarehouseSavedQueryDraft
}

export type SqlEditorSource = 'insight' | 'endpoint'

export interface SaveAsMenuItem {
    action: 'insight' | 'endpoint' | 'view'
    label: string
    dataAttr?: string
}

export interface SuggestionPayload {
    suggestedValue?: string
    originalValue?: string
    acceptText?: string
    rejectText?: string
    diffShowRunButton?: boolean
    source?: 'max_ai' | 'hogql_fixer'
    onAccept: (
        shouldRunQuery: boolean,
        actions: sqlEditorLogicType['actions'],
        values: sqlEditorLogicType['values'],
        props: sqlEditorLogicType['props']
    ) => void
    onReject: (
        actions: sqlEditorLogicType['actions'],
        values: sqlEditorLogicType['values'],
        props: sqlEditorLogicType['props']
    ) => void
}

export type UpdateViewPayload = Partial<DatabaseSchemaViewTable> & {
    edited_history_id?: string
    id: string
    lifecycle?: string
    shouldRematerialize?: boolean
    sync_frequency?: string
    types: string[][]
}

type LegacyDataVisualizationNode = DataVisualizationNode & { connectionId?: string }

function normalizeRawQuerySource(source: HogQLQuery): HogQLQuery {
    return {
        ...source,
        sendRawQuery: source.connectionId ? source.sendRawQuery || undefined : undefined,
    }
}

function sanitizeSourceQuery(sourceQuery: DataVisualizationNode): DataVisualizationNode {
    const { connectionId: _ignoredConnectionId, ...sanitizedSourceQuery } = sourceQuery as LegacyDataVisualizationNode

    return {
        ...sanitizedSourceQuery,
        source: normalizeRawQuerySource(sourceQuery.source),
    }
}

function toDataVisualizationNode(
    query: QueryBasedInsightModel['query'] | null | undefined
): DataVisualizationNode | undefined {
    if (!query) {
        return undefined
    }
    if (query.kind === NodeKind.DataVisualizationNode) {
        return query as DataVisualizationNode
    }
    // Insights created from the old DataTableNode path store the HogQLQuery under `.source`.
    // Wrap it so the SQL editor can render and save it through the visualization pipeline.
    if (query.kind === NodeKind.DataTableNode) {
        const source = (query as DataTableNode).source
        if (source?.kind === NodeKind.HogQLQuery) {
            return {
                kind: NodeKind.DataVisualizationNode,
                source: source as HogQLQuery,
            }
        }
    }
    return undefined
}

function getCurrentVisualizationQuery(
    dataLogicKey: string,
    fallbackQuery: DataVisualizationNode
): DataVisualizationNode {
    // This reads the mounted visualization state so save/update actions can include in-flight
    // axis/display edits. Those edits are also synced back through props.setQuery -> setSourceQuery,
    // so sourceQuery remains the durable fallback when the visualization logic is unmounted.
    const mountedVisualizationLogic = dataVisualizationLogic.findMounted({
        key: dataLogicKey,
    } as any)

    return mountedVisualizationLogic?.values.query ?? fallbackQuery
}

function getTabHash(values: sqlEditorLogicType['values']): Record<string, any> {
    const hash: Record<string, any> = {
        q: values.queryInput ?? '',
        output_tab: values.outputActiveTab,
    }
    const connectionId = values.sourceQuery?.source.connectionId
    if (values.featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] && connectionId) {
        hash['c'] = connectionId
        if (values.sourceQuery?.source.sendRawQuery) {
            hash['raw'] = '1'
        }
    }
    if (values.activeTab?.view) {
        hash['view'] = values.activeTab.view.id
    }
    if (values.activeTab?.insight) {
        hash['insight'] = values.activeTab.insight.short_id
    }
    if (values.activeTab?.draft) {
        hash['draft'] = values.activeTab.draft.id
    }

    return hash
}

function parseOutputTab(value: unknown): OutputTab | null {
    if (Object.values(OutputTab).includes(value as OutputTab)) {
        return value as OutputTab
    }

    return null
}

export function getDisplayTypeToSaveInsight(
    outputTab: OutputTab,
    sourceQueryDisplay: ChartDisplayType | undefined,
    effectiveVisualizationType?: ChartDisplayType
): ChartDisplayType {
    if (outputTab === OutputTab.Results) {
        return ChartDisplayType.ActionsTable
    }

    if (sourceQueryDisplay && sourceQueryDisplay !== ChartDisplayType.Auto) {
        return sourceQueryDisplay
    }

    return effectiveVisualizationType || ChartDisplayType.ActionsLineGraph
}

export function activeTabMatchesUrlTarget(
    activeTab: QueryTab | null,
    target: { draftId?: string; insightShortId?: string; viewId?: string }
): boolean {
    if (target.draftId) {
        return activeTab?.draft?.id === target.draftId
    }

    if (target.viewId) {
        return activeTab?.view?.id === target.viewId
    }

    if (target.insightShortId) {
        return activeTab?.insight?.short_id === target.insightShortId
    }

    return !activeTab?.draft && !activeTab?.view && !activeTab?.insight
}

export const sqlEditorLogic = kea<sqlEditorLogicType>([
    path(['data-warehouse', 'editor', 'sqlEditorLogic']),
    props({ mode: SQLEditorMode.FullScene } as SqlEditorLogicProps),
    tabAwareScene(),
    connect((props: SqlEditorLogicProps) => ({
        values: [
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryFolders', 'dataWarehouseSavedQueryMapById'],
            userLogic,
            ['user'],
            draftsLogic,
            ['drafts'],
            featureFlagLogic,
            ['featureFlags'],
            sourcesDataLogic,
            ['dataWarehouseSources'],
            databaseTableListLogic,
            ['database', 'databaseLoading'],
            outputPaneLogic({ tabId: props.tabId }),
            ['activeTab as outputActiveTab'],
            dataModelingLogic,
            ['dags', 'selectedDagId'],
        ],
        actions: [
            dataWarehouseViewsLogic,
            [
                'loadDataWarehouseSavedQueriesSuccess',
                'loadDataWarehouseSavedQueryFolders',
                'deleteDataWarehouseSavedQuerySuccess',
                'createDataWarehouseSavedQuerySuccess',
                'runDataWarehouseSavedQuery',
                'materializeDataWarehouseSavedQuery',
                'updateDataWarehouseSavedQuerySuccess',
                'updateDataWarehouseSavedQueryFailure',
                'updateDataWarehouseSavedQuery',
            ],
            outputPaneLogic({ tabId: props.tabId }),
            ['setActiveTab'],
            editorSceneLogic,
            ['reportAIQueryPrompted', 'reportAIQueryAccepted', 'reportAIQueryRejected', 'reportAIQueryPromptOpen'],
            fixSQLErrorsLogic,
            ['fixErrors', 'fixErrorsSuccess', 'fixErrorsFailure'],
            draftsLogic,
            ['saveAsDraft', 'deleteDraft', 'saveAsDraftSuccess', 'deleteDraftSuccess'],
            databaseTableListLogic,
            ['setConnection', 'loadDatabase'],
        ],
    })),
    actions(() => ({
        setSelectedQueryTablesAndColumns: (tablesAndColumns: Record<string, Record<string, boolean>>) => ({
            tablesAndColumns,
        }),
        setQueryInput: (queryInput: string | null) => ({ queryInput }),
        runQuery: (queryOverride?: string, switchTab?: boolean) => ({
            queryOverride,
            switchTab,
        }),
        createTab: (
            query?: string,
            view?: DataWarehouseSavedQuery,
            insight?: QueryBasedInsightModel,
            draft?: DataWarehouseSavedQueryDraft
        ) => ({
            query,
            view,
            insight,
            draft,
        }),
        updateTab: (tab: QueryTab) => ({ tab }),

        initialize: true,
        loadUpstream: (modelId: string) => ({ modelId }),
        saveAsView: (materializeAfterSave = false, fromDraft?: string) => ({ fromDraft, materializeAfterSave }),
        saveAsViewSubmit: (
            name: string,
            materializeAfterSave = false,
            fromDraft?: string,
            dagId?: string,
            folderId?: string | null,
            isTest = false
        ) => ({
            name,
            materializeAfterSave,
            fromDraft,
            dagId,
            folderId,
            isTest,
        }),
        saveAsInsight: true,
        saveAsInsightSubmit: (name: string) => ({ name }),
        saveAsEndpoint: true,
        saveAsEndpointSubmit: (name: string, description?: string, dagId?: string) => ({ name, description, dagId }),
        updateInsight: true,
        closeEditingObject: true,
        setFinishedLoading: (loading: boolean) => ({ loading }),
        setError: (error: string | null) => ({ error }),
        setDataError: (error: string | null) => ({ error }),
        setSourceQuery: (sourceQuery: DataVisualizationNode) => ({ sourceQuery }),
        setMetadata: (metadata: HogQLMetadataResponse | null) => ({ metadata }),
        setMetadataLoading: (loading: boolean) => ({ loading }),
        setInsightLoading: (loading: boolean) => ({ loading }),
        setViewLoading: (loading: boolean) => ({ loading }),
        setMaterializationModalOpen: (open: boolean) => ({ open }),
        setMaterializationModalView: (view: DataWarehouseSavedQuery | null) => ({ view }),
        editView: (query: string, view: DataWarehouseSavedQuery) => ({ query, view }),
        editInsight: (query: string, insight: QueryBasedInsightModel) => ({ query, insight }),
        setLastRunQuery: (lastRunQuery: DataVisualizationNode | null) => ({ lastRunQuery }),
        _setSuggestionPayload: (payload: SuggestionPayload | null) => ({ payload }),
        setSuggestedQueryInput: (suggestedQueryInput: string, source?: SuggestionPayload['source']) => ({
            suggestedQueryInput,
            source,
        }),
        onAcceptSuggestedQueryInput: (shouldRunQuery?: boolean) => ({ shouldRunQuery }),
        onRejectSuggestedQueryInput: true,
        shareTab: true,
        openHistoryModal: true,
        closeHistoryModal: true,
        setInProgressViewEdit: (viewId: string, historyId: string) => ({ viewId, historyId }),
        setInProgressViewEdits: (inProgressViewEdits: Record<DataWarehouseSavedQuery['id'], string>) => ({
            inProgressViewEdits,
        }),
        deleteInProgressViewEdit: (viewId: string) => ({ viewId }),
        setInProgressDraftEdit: (draftId: string, historyId: string) => ({ draftId, historyId }),
        setInProgressDraftEdits: (inProgressDraftEdits: Record<DataWarehouseSavedQueryDraft['id'], string>) => ({
            inProgressDraftEdits,
        }),
        deleteInProgressDraftEdit: (draftId: string) => ({ draftId }),
        updateView: (view: UpdateViewPayload, draftId?: string) => ({ view, draftId }),
        updateViewSuccess: (view: UpdateViewPayload, draftId?: string) => ({ view, draftId }),
        setUpstreamViewMode: (mode: 'graph' | 'table') => ({ mode }),
        setHoveredNode: (nodeId: string | null) => ({ nodeId }),
        saveDraft: (activeTab: QueryTab, queryInput: string, viewId: string) => ({
            activeTab,
            queryInput,
            viewId,
        }),
        syncUrlWithQuery: true,
        insertTextAtCursor: (text: string) => ({ text }),
        setEditorSource: (source: SqlEditorSource) => ({ source }),
        setSendRawQuery: (sendRawQuery: boolean) => ({ sendRawQuery }),
        setDashboardId: (dashboardId: number | null) => ({ dashboardId }),
        openMaterializationModal: (view?: DataWarehouseSavedQuery) => ({ view }),
        closeMaterializationModal: true,
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps.monaco && !oldProps.editor && props.monaco && props.editor) {
            actions.initialize()
        }
    }),
    loaders(() => ({
        upstream: [
            null as LineageGraph | null,
            {
                loadUpstream: async (payload: { modelId: string }) => {
                    return await api.upstream.get(payload.modelId)
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        selectedQueryTablesAndColumns: [
            {} as Record<string, Record<string, boolean>>,
            {
                setSelectedQueryTablesAndColumns: (_, { tablesAndColumns }) => tablesAndColumns,
            },
        ],
        finishedLoading: [
            true,
            {
                setFinishedLoading: (_, { loading }) => loading,
            },
        ],
        sourceQuery: [
            {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: '',
                },
                display: ChartDisplayType.Auto,
            } as DataVisualizationNode,
            {
                setSourceQuery: (_, { sourceQuery }) => sanitizeSourceQuery(sourceQuery),
            },
        ],
        lastRunQuery: [
            null as DataVisualizationNode | null,
            {
                setLastRunQuery: (_, { lastRunQuery }) => lastRunQuery,
            },
        ],
        queryInput: [
            null as string | null,
            {
                setQueryInput: (_, { queryInput }) => queryInput,
            },
        ],
        editorSource: [
            'insight' as SqlEditorSource,
            {
                setEditorSource: (_, { source }) => source,
            },
        ],
        dashboardId: [
            null as number | null,
            {
                setDashboardId: (_, { dashboardId }) => dashboardId,
            },
        ],
        materializationModalOpen: [
            false,
            {
                setMaterializationModalOpen: (_, { open }) => open,
                closeMaterializationModal: () => false,
            },
        ],
        materializationModalView: [
            null as DataWarehouseSavedQuery | null,
            {
                setMaterializationModalView: (_, { view }) => view,
                closeMaterializationModal: () => null,
            },
        ],
        editingInsight: [
            null as QueryBasedInsightModel | null,
            {
                updateTab: (_, { tab }) => tab.insight ?? null,
            },
        ],
        viewLoading: [
            false,
            {
                setViewLoading: (_, { loading }) => loading,
            },
        ],
        insightLoading: [
            false,
            {
                setInsightLoading: (_, { loading }) => loading,
            },
        ],
        activeTab: [
            null as QueryTab | null,
            {
                updateTab: (_, { tab }) => tab,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
            },
        ],
        metadataLoading: [
            true,
            {
                setMetadataLoading: (_, { loading }) => loading,
            },
        ],
        metadata: [
            null as HogQLMetadataResponse | null,
            {
                setMetadata: (_, { metadata }) => metadata,
            },
        ],
        editorKey: [`hogql-editor-${props.tabId}`, {}],
        suggestionPayload: [
            null as SuggestionPayload | null,
            {
                _setSuggestionPayload: (_, { payload }) => payload,
            },
        ],
        isHistoryModalOpen: [
            false as boolean,
            {
                openHistoryModal: () => true,
                closeHistoryModal: () => false,
            },
        ],
        // if a view edit starts, store the historyId in the state
        inProgressViewEdits: [
            {} as Record<DataWarehouseSavedQuery['id'], string>,
            {
                setInProgressViewEdit: (state, { viewId, historyId }) => ({
                    ...state,
                    [viewId]: historyId,
                }),
                deleteInProgressViewEdit: (state, { viewId }) => {
                    const newInProgressViewEdits = { ...state }
                    delete newInProgressViewEdits[viewId]
                    return newInProgressViewEdits
                },
                setInProgressViewEdits: (_, { inProgressViewEdits }) => inProgressViewEdits,
            },
        ],
        inProgressDraftEdits: [
            {} as Record<DataWarehouseSavedQueryDraft['id'], string>,
            {
                setInProgressDraftEdit: (state, { draftId, historyId }) => ({
                    ...state,
                    [draftId]: historyId,
                }),
                deleteInProgressDraftEdit: (state, { draftId }) => {
                    const newInProgressDraftEdits = { ...state }
                    delete newInProgressDraftEdits[draftId]
                    return newInProgressDraftEdits
                },
                setInProgressDraftEdits: (_, { inProgressDraftEdits }) => inProgressDraftEdits,
            },
        ],
        fixErrorsError: [
            null as string | null,
            {
                setQueryInput: () => null,
                fixErrorsFailure: (_, { error }) => error,
            },
        ],
        upstreamViewMode: [
            'graph' as 'graph' | 'table',
            {
                setUpstreamViewMode: (_: 'graph' | 'table', { mode }: { mode: 'graph' | 'table' }) => mode,
            },
        ],
        hoveredNode: [
            null as string | null,
            {
                setHoveredNode: (_, { nodeId }) => nodeId,
            },
        ],
    })),
    listeners(({ values, props, actions, asyncActions, cache }) => ({
        fixErrorsSuccess: ({ response }) => {
            actions.setSuggestedQueryInput(response.query, 'hogql_fixer')

            posthog.capture('ai-error-fixer-success', { trace_id: response.trace_id })
        },
        fixErrorsFailure: () => {
            posthog.capture('ai-error-fixer-failure')
        },
        insertTextAtCursor: ({ text }) => {
            const editor = props.editor
            if (!editor) {
                return
            }

            const position = editor.getPosition()
            if (!position) {
                return
            }

            editor.executeEdits('insert-variable', [
                {
                    range: {
                        startLineNumber: position.lineNumber,
                        startColumn: position.column,
                        endLineNumber: position.lineNumber,
                        endColumn: position.column,
                    },
                    text,
                },
            ])

            // Move cursor to end of inserted text
            editor.setPosition({
                lineNumber: position.lineNumber,
                column: position.column + text.length,
            })

            editor.focus()
        },
        shareTab: () => {
            const currentTab = values.activeTab
            if (!currentTab) {
                return
            }

            if (currentTab.insight) {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_insight', currentTab.insight.short_id)

                if (currentTab.insight.query?.kind === NodeKind.DataVisualizationNode) {
                    const query = (currentTab.insight.query as DataVisualizationNode).source.query
                    if (values.queryInput !== query) {
                        shareUrl.searchParams.set('open_query', values.queryInput ?? '')
                    }
                }

                void copyToClipboard(shareUrl.toString(), 'share link')
            } else if (currentTab.view) {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_view', currentTab.view.id)

                if (values.queryInput != currentTab.view.query?.query) {
                    shareUrl.searchParams.set('open_query', values.queryInput ?? '')
                }

                void copyToClipboard(shareUrl.toString(), 'share link')
            } else {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_query', values.queryInput ?? '')

                void copyToClipboard(shareUrl.toString(), 'share link')
            }
        },
        setSuggestedQueryInput: ({ suggestedQueryInput, source }) => {
            // If there's no active tab, create one first to ensure Monaco Editor is available
            if (!values.activeTab) {
                actions.createTab(suggestedQueryInput)
                return
            }

            // Always create suggestion payload when a new suggestion comes in, even for consecutive suggestions
            // Only skip diff mode if the editor is completely empty
            if (values.queryInput && values.queryInput.trim() !== '') {
                actions._setSuggestionPayload({
                    suggestedValue: suggestedQueryInput,
                    originalValue: values.queryInput, // Store the current content as original for diff mode
                    acceptText: aiSuggestionOnAcceptText,
                    rejectText: aiSuggestionOnRejectText,
                    onAccept: aiSuggestionOnAccept,
                    onReject: aiSuggestionOnReject,
                    source,
                    diffShowRunButton: true,
                })
            } else {
                actions.setQueryInput(suggestedQueryInput)
            }
        },
        onAcceptSuggestedQueryInput: ({ shouldRunQuery }) => {
            values.suggestionPayload?.onAccept(!!shouldRunQuery, actions, values, props)

            // Re-create the model to prevent it from being purged
            if (props.monaco && values.activeTab) {
                const existingModel = props.monaco.editor.getModel(values.activeTab.uri)
                if (!existingModel) {
                    const newModel = props.monaco.editor.createModel(
                        values.suggestedQueryInput,
                        'hogQL',
                        values.activeTab.uri
                    )
                    cache.createdModels = cache.createdModels || []
                    cache.createdModels.push(newModel)

                    initModel(
                        newModel,
                        codeEditorLogic({
                            key: `hogql-editor-${props.tabId}`,
                            query: values.suggestedQueryInput,
                            language: 'hogQL',
                        })
                    )

                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(newModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(newModel)
                    }
                } else {
                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(existingModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(existingModel)
                    }
                }
            }
            posthog.capture('sql-editor-accepted-suggestion', { source: values.suggestedSource })
            actions._setSuggestionPayload(null)
        },
        onRejectSuggestedQueryInput: () => {
            values.suggestionPayload?.onReject(actions, values, props)

            // Re-create the model to prevent it from being purged
            if (props.monaco && values.activeTab) {
                const existingModel = props.monaco.editor.getModel(values.activeTab.uri)
                if (!existingModel) {
                    const newModel = props.monaco.editor.createModel(
                        values.queryInput ?? '',
                        'hogQL',
                        values.activeTab.uri
                    )
                    cache.createdModels = cache.createdModels || []
                    cache.createdModels.push(newModel)
                    initModel(
                        newModel,
                        codeEditorLogic({
                            key: `hogql-editor-${props.tabId}`,
                            query: values.queryInput ?? '',
                            language: 'hogQL',
                        })
                    )

                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(newModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(newModel)
                    }
                } else {
                    // Handle both diff editor and regular editor
                    if (props.editor && 'getModifiedEditor' in props.editor) {
                        // It's a diff editor, set model on the modified editor
                        const modifiedEditor = (props.editor as any).getModifiedEditor()
                        modifiedEditor.setModel(existingModel)
                    } else {
                        // Regular editor
                        props.editor?.setModel(existingModel)
                    }
                }
            }
            posthog.capture('sql-editor-rejected-suggestion', { source: values.suggestedSource })
            actions._setSuggestionPayload(null)
        },
        editView: ({ query, view }) => {
            actions.createTab(query, view)
        },
        editInsight: ({ query, insight }) => {
            actions.createTab(query, undefined, insight)
        },
        createTab: async ({ query = '', view, insight, draft }) => {
            // Use tabId to ensure each browser tab has its own unique Monaco model
            const tabName = draft?.name || view?.name || insight?.name || NEW_QUERY
            const rawInsightVisualizationQuery = toDataVisualizationNode(insight?.query)
            const insightVisualizationQuery = rawInsightVisualizationQuery
                ? sanitizeSourceQuery(rawInsightVisualizationQuery)
                : undefined

            if (props.monaco) {
                const uri = props.monaco.Uri.parse(`tab-${props.tabId}`)
                let model = props.monaco.editor.getModel(uri)
                if (!model) {
                    model = props.monaco.editor.createModel(query, 'hogQL', uri)
                    cache.createdModels = cache.createdModels || []
                    cache.createdModels.push(model)
                    props.editor?.setModel(model)
                    initModel(
                        model,
                        codeEditorLogic({
                            key: `hogql-editor-${props.tabId}`,
                            query: values.sourceQuery?.source.query ?? '',
                            language: 'hogQL',
                        })
                    )
                }

                actions.updateTab({
                    uri,
                    view,
                    insight,
                    name: tabName,
                    sourceQuery: insightVisualizationQuery,
                    draft: draft,
                })
            }
            if (insightVisualizationQuery) {
                actions.setLastRunQuery(insightVisualizationQuery)
            }
            if (query) {
                actions.setQueryInput(query)
            } else if (draft) {
                actions.setQueryInput(draft.query.query)
            } else if (view) {
                actions.setQueryInput(view.query?.query ?? '')
            } else if (insightVisualizationQuery) {
                actions.setQueryInput(insightVisualizationQuery.source.query || '')
            }

            // Focus the editor after creating a new tab
            props.editor?.focus()
        },
        setSourceQuery: ({ sourceQuery }) => {
            if (!values.activeTab) {
                return
            }

            const nextSourceQuery = sanitizeSourceQuery(sourceQuery)
            const currentTab = values.activeTab
            if (currentTab) {
                actions.updateTab({
                    ...currentTab,
                    sourceQuery: nextSourceQuery,
                })
            }
        },
        setSendRawQuery: ({ sendRawQuery }) => {
            const currentSourceQuery = values.sourceQuery

            actions.setSourceQuery({
                ...currentSourceQuery,
                source: {
                    ...currentSourceQuery.source,
                    sendRawQuery: sendRawQuery || undefined,
                },
            })
            actions.syncUrlWithQuery()
        },
        initialize: async () => {
            actions.setFinishedLoading(false)
        },
        setQueryInput: async ({ queryInput }, breakpoint) => {
            const tablesAndColumns = await parseQueryTablesAndColumns(queryInput)
            await breakpoint()
            actions.setSelectedQueryTablesAndColumns(tablesAndColumns)
            cache.updateActiveQueryDecoration?.()

            // Keep suggestion payload active - let user make edits and then decide to approve/reject
            // if editing a view, track latest history id changes are based on
            if (values.activeTab?.view && values.activeTab?.view.query?.query) {
                if (queryInput === values.activeTab.view?.query?.query) {
                    actions.deleteInProgressViewEdit(values.activeTab.view.id)
                } else if (
                    !values.inProgressViewEdits[values.activeTab.view.id] &&
                    values.activeTab.view.latest_history_id
                ) {
                    actions.setInProgressViewEdit(values.activeTab.view.id, values.activeTab.view.latest_history_id)
                }
            }

            await breakpoint(500)

            actions.syncUrlWithQuery()
        },
        saveDraft: async ({ queryInput, viewId }) => {
            if (values.activeTab) {
                actions.saveAsDraft(
                    {
                        ...values.sourceQuery.source,
                        query: queryInput,
                    },
                    viewId,
                    values.activeTab
                )
            }
        },
        saveAsDraftSuccess: ({ draft, tab: tabToUpdate }) => {
            actions.updateTab({ ...tabToUpdate, name: draft.name, draft: draft })
        },
        runQuery: ({ queryOverride, switchTab }) => {
            const query = (queryOverride || values.queryInput) ?? ''

            const newSource = normalizeRawQuerySource({
                ...values.sourceQuery.source,
                query,
            })

            actions.setSourceQuery({
                ...values.sourceQuery,
                source: newSource,
            })
            actions.setLastRunQuery({
                ...values.sourceQuery,
                source: newSource,
            })
            if (!cache.umountDataNode) {
                cache.umountDataNode = dataNodeLogic({
                    key: values.dataLogicKey,
                    query: newSource,
                }).mount()
            }

            dataNodeLogic({
                key: values.dataLogicKey,
                query: newSource,
            }).actions.loadData(!switchTab ? 'force_async' : 'async', undefined, newSource)

            // Mark the first query task as complete when the query is run
            globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.RunFirstQuery)
        },
        saveAsView: async ({ fromDraft, materializeAfterSave = false }) => {
            const multiDagEnabled = !!values.featureFlags[FEATURE_FLAGS.DATA_MODELING_MULTI_DAG]

            // Ensure DAGs are loaded via dataModelingLogic
            if (multiDagEnabled && values.dags.length === 0) {
                await dataModelingLogic.asyncActions.loadDags()
            }

            const isStaff = values.user?.is_staff ?? false
            const folderOptions: { value: string | null; label: string }[] = [
                { value: null, label: 'No folder' },
                ...values.dataWarehouseSavedQueryFolders.map((folder) => ({
                    value: folder.id,
                    label: folder.name,
                })),
            ]
            const createFolderAndSelect = async (onSelect: (newValue: string | null) => void): Promise<void> => {
                LemonDialog.openForm({
                    title: 'New folder',
                    initialValues: { folderName: '' },
                    content: (
                        <LemonField name="folderName">
                            <LemonInput placeholder="Enter a folder name" autoFocus />
                        </LemonField>
                    ),
                    errors: {
                        folderName: (name) => (!name?.trim() ? 'You must enter a folder name' : undefined),
                    },
                    onSubmit: async ({ folderName }) => {
                        const folder = await api.dataWarehouseSavedQueryFolders.create({ name: folderName.trim() })
                        folderOptions.splice(folderOptions.length - 1, 0, {
                            value: folder.id,
                            label: folder.name,
                        })
                        actions.loadDataWarehouseSavedQueryFolders()
                        onSelect(folder.id)
                        lemonToast.success('Folder created')
                    },
                    shouldAwaitSubmit: true,
                })
            }

            LemonDialog.openForm({
                title: 'Save as view',
                initialValues: {
                    viewName: values.activeTab?.name || '',
                    folderId: null,
                    isTest: false,
                    dagId: multiDagEnabled
                        ? (values.dags.find((d) => d.id === values.selectedDagId)?.id ?? values.dags[0]?.id ?? null)
                        : undefined,
                },
                description: `View names can only contain letters, numbers, '_', or '$'. Spaces are not allowed.`,
                content: (isLoading) =>
                    isLoading ? (
                        <div className="h-[37px] flex items-center">
                            <ViewEmptyState />
                        </div>
                    ) : (
                        <>
                            <LemonField name="viewName">
                                <LemonInput
                                    data-attr="sql-editor-input-save-view-name"
                                    disabled={isLoading}
                                    placeholder="Please enter the name of the view"
                                    autoFocus
                                />
                            </LemonField>
                            <div className="flex gap-2 mt-2">
                                <LemonField name="folderId" label="Add to folder" className="flex-1">
                                    {({ value, onChange }) => (
                                        <LemonSelect<string | null>
                                            value={value}
                                            onChange={onChange}
                                            options={[
                                                ...folderOptions,
                                                {
                                                    value: '__add_new_folder__',
                                                    label: '+ Add new folder',
                                                    labelInMenu: () => (
                                                        <button
                                                            type="button"
                                                            className="w-full text-left text-primary px-2 py-1.5"
                                                            onClick={() => createFolderAndSelect(onChange)}
                                                        >
                                                            + Add new folder
                                                        </button>
                                                    ),
                                                },
                                            ]}
                                            disabled={isLoading}
                                            placeholder="Select a folder"
                                            fullWidth
                                        />
                                    )}
                                </LemonField>
                                {multiDagEnabled && (
                                    <LemonField name="dagId" label="Add to DAG" className="flex-1">
                                        {({ value: dagId, onChange: setDagId }) => (
                                            <DagSelector
                                                selectedDagId={dagId}
                                                onSelectDag={setDagId}
                                                onCreateDag={(onSelect) => {
                                                    openCreateDagDialog({
                                                        existingNames: new Set(
                                                            dataModelingLogic.values.dags.map((d) => d.name)
                                                        ),
                                                        onSubmit: async (dagData) => {
                                                            const newDag = await api.dataModelingDags.create(dagData)
                                                            await dataModelingLogic.asyncActions.loadDags()
                                                            onSelect(newDag.id)
                                                            lemonToast.success('DAG created')
                                                        },
                                                    })
                                                }}
                                            />
                                        )}
                                    </LemonField>
                                )}
                            </div>
                            {isStaff && (
                                <LemonField name="isTest" className="mt-2">
                                    {({ value, onChange }) => (
                                        <div className="flex items-center gap-2">
                                            <LemonCheckbox
                                                checked={value}
                                                onChange={onChange}
                                                data-attr="sql-editor-input-save-view-is-test"
                                                label="Is this view for testing only?"
                                            />
                                            <Tooltip title="Test views and any downstream assets that depend on them will be automatically deleted after 1 week.">
                                                <span className="text-muted cursor-pointer">&#9432;</span>
                                            </Tooltip>
                                        </div>
                                    )}
                                </LemonField>
                            )}
                        </>
                    ),
                errors: {
                    viewName: (name) =>
                        !name
                            ? 'You must enter a name'
                            : !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)
                              ? 'Name must be valid'
                              : undefined,
                    dagId: (dagId) => (multiDagEnabled && !dagId ? 'Please select a DAG' : undefined),
                },
                onSubmit: async ({ viewName, dagId, folderId, isTest }) => {
                    await asyncActions.saveAsViewSubmit(
                        viewName,
                        materializeAfterSave,
                        fromDraft,
                        dagId,
                        folderId,
                        isTest ?? false
                    )
                    if (multiDagEnabled && dagId) {
                        dataModelingLogic.actions.setSelectedDagId(dagId)
                    }
                },
                shouldAwaitSubmit: true,
            })
        },
        saveAsViewSubmit: async ({
            name,
            materializeAfterSave = false,
            fromDraft,
            dagId,
            isTest = false,
            folderId,
        }) => {
            const query: HogQLQuery = values.sourceQuery.source

            const queryToSave = normalizeRawQuerySource({
                ...query,
                query: values.queryInput ?? '',
            })

            const logic = dataNodeLogic({
                key: values.dataLogicKey,
                query: queryToSave,
            })

            const response = logic.values.response
            const types = response && 'types' in response ? (response.types ?? []) : []
            try {
                await dataWarehouseViewsLogic.asyncActions.createDataWarehouseSavedQuery({
                    name,
                    query: queryToSave,
                    types,
                    ...(folderId ? { folder_id: folderId } : {}),
                    ...(dagId ? { dag_id: dagId } : {}),
                    ...(isTest ? { is_test: true } : {}),
                })

                // Saved queries are unique by team,name
                const savedQuery = dataWarehouseViewsLogic.values.dataWarehouseSavedQueries.find((q) => q.name === name)

                if (materializeAfterSave && savedQuery) {
                    await dataWarehouseViewsLogic.asyncActions.materializeDataWarehouseSavedQuery(savedQuery.id)
                }

                if (fromDraft) {
                    actions.deleteDraft(fromDraft, savedQuery?.name)
                }

                // reload DAGs so newly created default DAG appears
                dataModelingLogic.findMounted()?.actions.loadDags()
            } catch {
                lemonToast.error('Failed to save view')
            }
        },
        openMaterializationModal: async ({ view }, breakpoint) => {
            if (!view) {
                return
            }

            await breakpoint(100)

            if (values.materializationModalView?.id === view.id) {
                actions.setMaterializationModalOpen(true)
                return
            }

            actions.setViewLoading(true)

            try {
                let nextView = view

                if (!nextView.query) {
                    nextView = await api.dataWarehouseSavedQueries.get(view.id)
                }

                await breakpoint(100)
                actions.setMaterializationModalView(nextView)
                actions.setMaterializationModalOpen(true)
            } catch {
                lemonToast.error('View not found')
                actions.closeMaterializationModal()
            } finally {
                actions.setViewLoading(false)
            }
        },
        saveAsInsight: async () => {
            const currentVisualizationQuery = getCurrentVisualizationQuery(values.dataLogicKey, values.sourceQuery)
            const effectiveVisualizationType = dataVisualizationLogic.findMounted({
                key: values.dataLogicKey,
                query: currentVisualizationQuery,
                dataNodeCollectionId: values.dataLogicKey,
                editMode: true,
            })?.values.effectiveVisualizationType

            const defaultDisplay = getDisplayTypeToSaveInsight(
                values.outputActiveTab,
                currentVisualizationQuery.display,
                effectiveVisualizationType
            )

            LemonDialog.openForm({
                title: 'Save as new insight',
                initialValues: {
                    name: '',
                },
                content: (
                    <>
                        <LemonField name="name">
                            <LemonInput data-attr="insight-name" placeholder="Please enter the new name" autoFocus />
                        </LemonField>
                        <div className="mt-3">
                            <div className="text-muted text-xs mb-1">Preview</div>
                            <div className="bg-bg-light max-h-[60vh] overflow-auto">
                                <Query
                                    readOnly
                                    embedded
                                    query={{
                                        ...currentVisualizationQuery,
                                        display: defaultDisplay,
                                    }}
                                />
                            </div>
                        </div>
                    </>
                ),
                errors: {
                    name: (name) => (!name ? 'You must enter a name' : undefined),
                },
                onSubmit: async ({ name }) => actions.saveAsInsightSubmit(name),
            })
        },
        saveAsInsightSubmit: async ({ name }) => {
            const currentVisualizationQuery = getCurrentVisualizationQuery(values.dataLogicKey, values.sourceQuery)
            const effectiveVisualizationType = dataVisualizationLogic.findMounted({
                key: values.dataLogicKey,
                query: currentVisualizationQuery,
                dataNodeCollectionId: values.dataLogicKey,
                editMode: true,
            })?.values.effectiveVisualizationType

            const display = getDisplayTypeToSaveInsight(
                values.outputActiveTab,
                currentVisualizationQuery.display,
                effectiveVisualizationType
            )

            const dashboardId = values.dashboardId
            const insight = await insightsApi.create({
                name,
                query: { ...currentVisualizationQuery, display } as DataVisualizationNode,
                saved: true,
                ...(dashboardId ? { dashboards: [dashboardId] } : {}),
            })
            const logic = insightLogic({
                dashboardItemId: insight.short_id,
                doNotLoad: true,
            })
            const umount = logic.mount()
            logic.actions.setInsight(insight, { fromPersistentApi: true, overrideQuery: true })
            const timeoutId = window.setTimeout(() => umount(), 1000 * 10) // keep mounted for 10 seconds while we redirect
            cache.timeouts = cache.timeouts || []
            cache.timeouts.push(timeoutId)

            if (dashboardId) {
                dashboardsModel.findMounted()?.actions.updateDashboardInsight(insight)
                dashboardLogic
                    .findMounted({ id: dashboardId })
                    ?.actions.loadDashboard({ action: DashboardLoadAction.Update })
                lemonToast.success('Insight saved & added to dashboard', {
                    button: {
                        label: 'View Insights list',
                        action: () => router.actions.push(urls.savedInsights()),
                    },
                })
                actions.setDashboardId(null)
                router.actions.push(urls.dashboard(dashboardId, insight.short_id))
            } else {
                lemonToast.info(`You're now viewing ${insight.name || insight.derived_name || name}`)
                router.actions.push(urls.insightView(insight.short_id))
            }
        },
        saveAsEndpoint: async () => {
            LemonDialog.openForm({
                title: 'Save as endpoint',
                initialValues: {
                    name: '',
                    description: '',
                },
                content: (
                    <>
                        <LemonField name="name">
                            <LemonInput
                                data-attr="endpoint-name"
                                placeholder="Please enter the endpoint name"
                                autoFocus
                            />
                        </LemonField>
                        <LemonField name="description" className="mt-2">
                            <LemonInput
                                data-attr="endpoint-description"
                                placeholder="Please enter a description (optional)"
                            />
                        </LemonField>
                    </>
                ),
                errors: {
                    name: (name) => validateEndpointName(name?.trim() || ''),
                },
                onSubmit: async ({ name, description }) => actions.saveAsEndpointSubmit(name, description),
            })
        },
        saveAsEndpointSubmit: async ({ name, description }) => {
            try {
                const endpoint = await api.endpoint.create({
                    name: slugify(name),
                    description: description || undefined,
                    query: normalizeRawQuerySource({
                        ...(values.sourceQuery.source as HogQLQuery),
                        query: values.queryInput ?? '',
                    }),
                })
                lemonToast.success('Endpoint created')
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateFirstEndpoint)
                router.actions.push(urls.endpoint(endpoint.name))
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to create endpoint')
            }
        },
        updateInsight: async () => {
            if (!values.editingInsight) {
                return
            }

            actions.setInsightLoading(true)

            const insightName = values.activeTab?.name
            const currentVisualizationQuery = getCurrentVisualizationQuery(values.dataLogicKey, values.sourceQuery)

            const insightRequest: Partial<QueryBasedInsightModel> = {
                name: insightName ?? values.editingInsight.name,
                query: currentVisualizationQuery,
            }

            let savedInsight: QueryBasedInsightModel
            try {
                savedInsight = await insightsApi.update(values.editingInsight.id, insightRequest)
            } catch (e) {
                actions.setInsightLoading(false)
                if (e instanceof ApiError) {
                    lemonToast.error(e.detail ?? 'Could not update insight')
                } else {
                    lemonToast.error('Could not update insight')
                }
                throw e
            }
            actions.setInsightLoading(false)

            if (values.activeTab) {
                actions.updateTab({
                    ...values.activeTab,
                    insight: savedInsight,
                })
            }
            const loadedLogic = insightLogic.findMounted({
                dashboardItemId: values.editingInsight.short_id,
                dashboardId: undefined,
            })
            if (loadedLogic) {
                loadedLogic.actions.setInsight(savedInsight, { overrideQuery: true, fromPersistentApi: true })
            }

            const dashboardId = values.dashboardId
            if (dashboardId) {
                dashboardsModel.findMounted()?.actions.updateDashboardInsight(savedInsight)
                dashboardLogic
                    .findMounted({ id: dashboardId })
                    ?.actions.loadDashboard({ action: DashboardLoadAction.Update })
                lemonToast.success('Insight updated', {
                    button: {
                        label: 'View Insights list',
                        action: () => router.actions.push(urls.savedInsights()),
                    },
                })
                actions.setDashboardId(null)
                router.actions.push(urls.dashboard(dashboardId, savedInsight.short_id))
            } else {
                lemonToast.info(
                    `You're now viewing ${savedInsight.name || savedInsight.derived_name || insightName || 'Untitled'}`
                )
                router.actions.push(urls.insightView(savedInsight.short_id))
            }
        },
        closeEditingObject: () => {
            actions.setInsightLoading(false)
            actions.setViewLoading(false)

            if (!values.activeTab) {
                actions.createTab(values.queryInput ?? '')
                return
            }

            const nextActiveTab = {
                ...values.activeTab,
                name: NEW_QUERY,
                view: undefined,
                insight: undefined,
                draft: undefined,
            }

            actions.updateTab(nextActiveTab)

            if (!values.isEmbeddedMode) {
                const nextHash = encodeURIComponent(JSON.stringify(getTabHash({ ...values, activeTab: nextActiveTab })))
                const currentUrl = new URL(window.location.href)
                currentUrl.searchParams.delete('open_insight')
                currentUrl.searchParams.delete('open_view')
                currentUrl.searchParams.delete('open_draft')
                window.history.replaceState(
                    {},
                    '',
                    `${urls.sqlEditor()}${currentUrl.searchParams.toString() ? `?${currentUrl.searchParams.toString()}` : ''}#${nextHash}`
                )
            }
        },
        loadDataWarehouseSavedQueriesSuccess: ({ dataWarehouseSavedQueries }) => {
            if (values.activeTab?.view) {
                const updatedView = dataWarehouseSavedQueries.find((v) => v.id === values.activeTab?.view?.id)
                if (updatedView && values.activeTab) {
                    // Preserve the query from the active tab since list response doesn't include it
                    const viewWithQuery = { ...updatedView, query: values.activeTab.view.query }
                    actions.updateTab({ ...values.activeTab, view: viewWithQuery })
                }
            }
        },
        deleteDataWarehouseSavedQuerySuccess: ({ payload: viewId }) => {
            if (values.activeTab?.view?.id === viewId && !values.activeTab?.draft) {
                actions.createTab()
            }
        },
        createDataWarehouseSavedQuerySuccess: ({ dataWarehouseSavedQueries, payload: view }) => {
            const newView = view && dataWarehouseSavedQueries.find((v) => v.name === view.name)
            if (newView) {
                const oldTab = values.activeTab
                // Only update the tab if it doesn't have a view (new query being saved)
                // or if it's the same view being recreated (edge case)
                if (oldTab && (!oldTab.view || oldTab.view.id === newView.id)) {
                    actions.updateTab({ ...oldTab, view: newView })
                }
            }
        },
        updateView: async ({ view, draftId }) => {
            const latestView = await api.dataWarehouseSavedQueries.get(view.id)
            // Only check for conflicts if there's an activity log (latest_history_id exists)
            // When there's no activity log, both edited_history_id and latest_history_id are null/undefined,
            // and we should allow the update to proceed without showing a false conflict
            if (
                latestView?.latest_history_id != null &&
                view.edited_history_id !== latestView.latest_history_id &&
                view.query?.query !== latestView?.query?.query
            ) {
                actions._setSuggestionPayload({
                    suggestedValue: values.queryInput!,
                    originalValue: latestView?.query?.query,
                    acceptText: 'Confirm changes',
                    rejectText: 'Cancel',
                    diffShowRunButton: false,
                    onAccept: async () => {
                        actions.setQueryInput(view.query?.query ?? '')
                        await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery({
                            ...view,
                            edited_history_id: latestView?.latest_history_id,
                        })
                        actions.updateViewSuccess(view, draftId)
                    },
                    onReject: () => {},
                })
                lemonToast.error('View has been edited by another user. Review changes to update.')
            } else {
                await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery(view)
                actions.updateViewSuccess(view, draftId)
            }
        },
        updateViewSuccess: ({ view, draftId }) => {
            if (draftId) {
                actions.deleteDraft(draftId, view?.name)
            }
        },
        deleteDraftSuccess: ({ draftId, viewName }) => {
            if (values.activeTab && values.activeTab.draft?.id === draftId) {
                actions.updateTab({
                    ...values.activeTab,
                    draft: undefined,
                    name: viewName ?? values.activeTab.name,
                })
            }
        },
    })),
    subscriptions(({ actions, values, cache }) => ({
        showLegacyFilters: (showLegacyFilters: boolean) => {
            if (showLegacyFilters) {
                if (typeof values.sourceQuery.source.filters !== 'object') {
                    actions.setSourceQuery({
                        ...values.sourceQuery,
                        source: {
                            ...values.sourceQuery.source,
                            filters: {},
                        },
                    })
                }
            } else {
                if (values.sourceQuery.source.filters !== undefined) {
                    actions.setSourceQuery({
                        ...values.sourceQuery,
                        source: {
                            ...values.sourceQuery.source,
                            filters: undefined,
                        },
                    })
                }
            }
        },
        editingView: (editingView) => {
            if (editingView) {
                actions.loadUpstream(editingView.id)
            }
        },
        drafts: (drafts) => {
            if (values.activeTab && values.activeTab.draft) {
                const updatedDraft = drafts.find(
                    (d: DataWarehouseSavedQueryDraft) => d.id === values.activeTab?.draft?.id
                )
                if (updatedDraft) {
                    actions.updateTab({
                        ...values.activeTab,
                        draft: updatedDraft,
                        name: updatedDraft.name ?? values.activeTab.view?.name ?? values.activeTab.name,
                    })
                }
            }
        },
        selectedConnectionId: (selectedConnectionId) => {
            if (cache.lastSelectedConnectionId === selectedConnectionId) {
                return
            }

            cache.lastSelectedConnectionId = selectedConnectionId
            actions.setConnection(selectedConnectionId ?? null)
            actions.loadDatabase()
        },
    })),
    selectors({
        suggestedSource: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.source ?? null
            },
        ],
        diffShowRunButton: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.diffShowRunButton
            },
        ],
        acceptText: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.acceptText ?? 'Accept'
            },
        ],
        rejectText: [
            (s) => [s.suggestionPayload],
            (suggestionPayload) => {
                return suggestionPayload?.rejectText ?? 'Reject'
            },
        ],

        suggestedQueryInput: [
            (s) => [s.suggestionPayload, s.queryInput],
            (suggestionPayload, queryInput) => {
                if (suggestionPayload?.suggestedValue && suggestionPayload?.suggestedValue !== queryInput) {
                    return suggestionPayload?.suggestedValue ?? ''
                }

                return queryInput ?? ''
            },
        ],
        originalQueryInput: [
            (s) => [s.suggestionPayload, s.queryInput],
            (suggestionPayload, queryInput) => {
                // If we have a suggestion payload, always show diff mode
                if (suggestionPayload?.suggestedValue) {
                    // Prefer the stored originalValue if available, otherwise use current queryInput
                    return suggestionPayload?.originalValue || queryInput
                }

                return undefined
            },
        ],
        editingView: [
            (s) => [s.activeTab],
            (activeTab) => {
                return activeTab?.view
            },
        ],
        changesToSave: [
            (s) => [s.editingView, s.queryInput],
            (editingView, queryInput) => {
                return editingView?.query?.query !== queryInput
            },
        ],
        exportContext: [
            (s) => [s.sourceQuery],
            (sourceQuery) => {
                // TODO: use active tab at some point
                const filename = 'export'

                return {
                    ...queryExportContext(sourceQuery.source, undefined, undefined),
                    filename,
                } as ExportContext
            },
        ],
        selectedConnectionId: [
            (s) => [s.sourceQuery, s.featureFlags],
            (sourceQuery, featureFlags) => {
                if (!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]) {
                    return undefined
                }
                return sourceQuery.source && 'connectionId' in sourceQuery.source
                    ? sourceQuery.source.connectionId
                    : undefined
            },
        ],
        selectedDirectSource: [
            (s) => [s.dataWarehouseSources, s.selectedConnectionId],
            (dataWarehouseSources, selectedConnectionId): ExternalDataSource | undefined => {
                return dataWarehouseSources?.results.find((source) => source.id === selectedConnectionId)
            },
        ],
        sendRawQueryEnabled: [
            (s) => [s.sourceQuery, s.selectedConnectionId],
            (sourceQuery, selectedConnectionId) => !!selectedConnectionId && (sourceQuery.source.sendRawQuery ?? false),
        ],
        isEditingMaterializedView: [
            (s) => [s.editingView],
            (editingView) => {
                return !!editingView?.is_materialized
            },
        ],
        isSourceQueryLastRun: [
            (s) => [s.queryInput, s.lastRunQuery, s.sourceQuery],
            (queryInput, lastRunQuery, sourceQuery) => {
                const lastRunQueryText = lastRunQuery?.source.query ?? sourceQuery.source.query
                return queryInput === lastRunQueryText
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
                    !isEqual(sourceQueryWithoutUndefinedAndNullKeys, removeUndefinedAndNull(editingInsightQuery))
                )
            },
        ],
        showLegacyFilters: [
            (s) => [s.queryInput],
            (queryInput) => {
                return queryInput && (queryInput.indexOf('{filters}') !== -1 || queryInput.indexOf('{filters.') !== -1)
            },
        ],
        hasQueryInput: [(s) => [s.queryInput], (queryInput) => !!queryInput],
        isEmbeddedMode: [
            () => [(_, p: SqlEditorLogicProps) => p.mode],
            (mode) => isEmbeddedSQLEditorMode(mode ?? SQLEditorMode.FullScene),
        ],
        dataLogicKey: [(_, p) => [p.tabId], (tabId) => `data-warehouse-editor-data-node-${tabId}`],
        isDraft: [(s) => [s.activeTab], (activeTab) => (activeTab ? !!activeTab.draft?.id : false)],
        currentDraft: [(s) => [s.activeTab], (activeTab) => (activeTab ? activeTab.draft : null)],
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
                            path: urls.sqlEditor({ insightShortId: insight.short_id }),
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
                        resourceType: { type: editingView.is_materialized ? 'matview' : 'view' },
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
            (s) => [s.editorSource, s.dashboardId],
            (editorSource, dashboardId): { primary: SaveAsMenuItem; secondary: SaveAsMenuItem[] } => {
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

                if (editorSource === 'endpoint') {
                    return {
                        primary: saveAsEndpointItem,
                        secondary: [saveAsInsightItem, saveAsViewItem],
                    }
                }

                return {
                    primary: saveAsInsightItem,
                    secondary: [saveAsEndpointItem, saveAsViewItem],
                }
            },
        ],

        selectedQueryColumns: [
            (s) => [s.selectedQueryTablesAndColumns],
            (tablesAndColumns: Record<string, Record<string, boolean>>): Record<string, boolean> => {
                return Object.fromEntries(
                    Object.entries(tablesAndColumns).flatMap(([table, columns]) => {
                        return Object.keys(columns).map((column) => [`${table}.${column}`, true])
                    })
                )
            },
            { resultEqualityCheck: objectsEqual },
        ],
    }),
    tabAwareActionToUrl(({ values }) => ({
        syncUrlWithQuery: () => {
            if (values.isEmbeddedMode) {
                return
            }
            return [urls.sqlEditor(), undefined, getTabHash(values), { replace: true }]
        },
        createTab: () => {
            if (values.isEmbeddedMode) {
                return
            }
            return [urls.sqlEditor(), undefined, getTabHash(values), { replace: true }]
        },
        setActiveTab: () => {
            if (values.isEmbeddedMode || !values.activeTab) {
                return
            }
            return [urls.sqlEditor(), undefined, getTabHash(values), { replace: true }]
        },
    })),
    tabAwareUrlToAction(({ actions, values, props }) => ({
        [urls.sqlEditor()]: async (_, searchParams, hashParams) => {
            if (isEmbeddedSQLEditorMode(props.mode ?? SQLEditorMode.FullScene)) {
                return
            }

            if (searchParams.source === 'endpoint' || searchParams.source === 'insight') {
                actions.setEditorSource(searchParams.source)
            }
            if (searchParams.dashboard) {
                const parsed = parseInt(searchParams.dashboard, 10)
                if (!isNaN(parsed)) {
                    actions.setDashboardId(parsed)
                }
            }

            const outputTabFromUrl = parseOutputTab(searchParams.output_tab ?? hashParams.output_tab)

            if (
                !searchParams.open_query &&
                !searchParams.open_view &&
                !searchParams.open_insight &&
                !searchParams.open_draft &&
                !searchParams.output_tab &&
                !hashParams.q &&
                !hashParams.c &&
                !hashParams.raw &&
                !hashParams.view &&
                !hashParams.insight &&
                !hashParams.draft &&
                !hashParams.output_tab &&
                values.queryInput !== null
            ) {
                return
            }

            const connectionIdFromHash =
                values.featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] &&
                typeof hashParams.c === 'string' &&
                hashParams.c !== ''
                    ? hashParams.c
                    : undefined
            const sendRawQueryFromHash =
                connectionIdFromHash !== undefined &&
                values.featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] &&
                String(hashParams.raw) === '1'
            const currentConnectionId = values.sourceQuery.source.connectionId || undefined
            const currentSendRawQuery = values.sourceQuery.source.sendRawQuery ?? false

            if (connectionIdFromHash !== currentConnectionId || sendRawQueryFromHash !== currentSendRawQuery) {
                actions.setSourceQuery({
                    ...values.sourceQuery,
                    source: {
                        ...values.sourceQuery.source,
                        connectionId: connectionIdFromHash,
                        sendRawQuery: sendRawQueryFromHash || undefined,
                    },
                })
            }

            let tabAdded = false

            const createQueryTab = async (): Promise<void> => {
                if (outputTabFromUrl && values.outputActiveTab !== outputTabFromUrl) {
                    actions.setActiveTab(outputTabFromUrl)
                }
                const draftIdFromUrl = searchParams.open_draft || hashParams.draft
                const viewIdFromUrl = searchParams.open_view || hashParams.view
                const insightShortIdFromUrl = searchParams.open_insight || hashParams.insight

                if (
                    draftIdFromUrl &&
                    (searchParams.open_draft ||
                        !activeTabMatchesUrlTarget(values.activeTab, {
                            draftId: draftIdFromUrl,
                        }))
                ) {
                    const draftId = draftIdFromUrl
                    const draft = values.drafts.find((draft) => {
                        return draft.id === draftId
                    })

                    if (!draft) {
                        lemonToast.error('Draft not found')
                        return
                    }

                    const existingTab = values.activeTab?.draft?.id === draft.id ? values.activeTab : null

                    if (!existingTab) {
                        const associatedView = draft.saved_query_id
                            ? values.dataWarehouseSavedQueryMapById[draft.saved_query_id]
                            : undefined

                        actions.createTab(draft.query.query, associatedView, undefined, draft)
                    }
                    return
                } else if (
                    viewIdFromUrl &&
                    (searchParams.open_view ||
                        !activeTabMatchesUrlTarget(values.activeTab, {
                            viewId: viewIdFromUrl,
                        }))
                ) {
                    // Open view
                    const viewId = viewIdFromUrl

                    actions.setViewLoading(true)

                    if (values.dataWarehouseSavedQueries.length === 0) {
                        await dataWarehouseViewsLogic.asyncActions.loadDataWarehouseSavedQueries()
                    }

                    let view = values.dataWarehouseSavedQueries.find((n) => n.id === viewId)
                    if (!view) {
                        lemonToast.error('View not found')
                        actions.setViewLoading(false)
                        return
                    }

                    // Fetch the full view with query if not already loaded
                    if (!view.query) {
                        try {
                            view = await api.dataWarehouseSavedQueries.get(viewId)
                        } catch {
                            lemonToast.error('Failed to load view details')
                            actions.setViewLoading(false)
                            return
                        }
                    }

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : (view.query?.query ?? '')

                    if (outputTabFromUrl) {
                        actions.createTab(queryToOpen, view)
                    } else {
                        actions.editView(queryToOpen, view)
                    }
                    actions.setViewLoading(false)
                    tabAdded = true
                    router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                } else if (
                    insightShortIdFromUrl &&
                    (searchParams.open_insight ||
                        !activeTabMatchesUrlTarget(values.activeTab, {
                            insightShortId: insightShortIdFromUrl,
                        }))
                ) {
                    // reset current tab
                    if (values.activeTab) {
                        actions.updateTab({ ...values.activeTab, insight: undefined })
                    }
                    actions._setSuggestionPayload(null)

                    const shortId = insightShortIdFromUrl
                    if (shortId === 'new') {
                        // Add new blank tab
                        actions.createTab()
                        tabAdded = true
                        router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                        return
                    }

                    // Open Insight
                    actions.setInsightLoading(true)
                    let insight: QueryBasedInsightModel | null
                    try {
                        insight = await insightsApi.getByShortId(shortId, undefined, 'async')
                    } catch {
                        actions.setInsightLoading(false)
                        lemonToast.error('Insight not found')
                        return
                    }
                    actions.setInsightLoading(false)
                    if (!insight) {
                        lemonToast.error('Insight not found')
                        return
                    }

                    const insightVisualizationQuery = toDataVisualizationNode(insight.query)
                    const query = insightVisualizationQuery?.source.query ?? ''

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : query

                    if (insightVisualizationQuery) {
                        actions.setSourceQuery(insightVisualizationQuery)
                    }
                    actions.editInsight(queryToOpen, insight)
                    if (!outputTabFromUrl) {
                        actions.setActiveTab(OutputTab.Visualization)
                    }

                    // Only run the query if the results aren't already cached locally and we're not using the open_query search param
                    if (insightVisualizationQuery && !searchParams.open_query) {
                        const mountedDataLogic = dataNodeLogic.findMounted({ key: values.dataLogicKey })
                        const response = mountedDataLogic?.values.response
                        const responseLoading = mountedDataLogic?.values.responseLoading ?? false

                        if (!responseLoading && !response) {
                            actions.runQuery()
                        }
                    } else {
                        actions.runQuery()
                    }

                    tabAdded = true
                    router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                } else if (searchParams.open_query) {
                    // Open query string
                    actions.createTab(searchParams.open_query)
                    tabAdded = true
                } else if (
                    hashParams.q &&
                    !draftIdFromUrl &&
                    !viewIdFromUrl &&
                    !insightShortIdFromUrl &&
                    (values.queryInput === null ||
                        !activeTabMatchesUrlTarget(values.activeTab, {}) ||
                        values.queryInput !== hashParams.q)
                ) {
                    actions.createTab(hashParams.q)
                    tabAdded = true
                } else if (values.queryInput === null) {
                    actions.createTab('')
                    tabAdded = true
                }
            }

            if (props.monaco) {
                await createQueryTab()
            } else {
                const waitUntilMonaco = async (): Promise<void> => {
                    return await new Promise((resolve, reject) => {
                        let intervalCount = 0
                        const interval = setInterval(() => {
                            intervalCount++

                            if (props.monaco && !tabAdded) {
                                clearInterval(interval)
                                resolve()
                            } else if (intervalCount >= 10_000 / 300) {
                                clearInterval(interval)
                                reject()
                            }
                        }, 300)
                    })
                }

                try {
                    await waitUntilMonaco()
                    await createQueryTab()
                } catch {
                    // Monaco timed out - still try to create tab if monaco loaded late
                    if (props.monaco) {
                        await createQueryTab()
                    }
                }
            }

            if (!values.database && !values.databaseLoading && connectionIdFromHash === undefined) {
                actions.setConnection(values.selectedConnectionId ?? null)
                actions.loadDatabase()
            }
        },
    })),
    afterMount(({ actions, props, values, cache }) => {
        cache.lastSelectedConnectionId = values.selectedConnectionId

        if (
            isEmbeddedSQLEditorMode(props.mode ?? SQLEditorMode.FullScene) &&
            !values.database &&
            !values.databaseLoading
        ) {
            actions.setConnection(values.selectedConnectionId ?? null)
            actions.loadDatabase()
        }
    }),
    beforeUnmount(({ cache }) => {
        cache.umountDataNode?.()

        cache.createdModels?.forEach((m: editor.ITextModel) => {
            try {
                m.dispose()
            } catch {}
        })
        cache.createdModels = []

        const timeouts = cache.timeouts as Array<number> | undefined
        timeouts?.forEach((t) => {
            try {
                clearTimeout(t)
            } catch {}
        })
        cache.timeouts = []
    }),
])
