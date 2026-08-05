import { Monaco } from '@monaco-editor/react'
import { deepEqual as equal } from 'fast-equals'
import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { type IRange, Uri, editor } from 'monaco-editor'
import posthog from 'posthog-js'
import { Suspense } from 'react'

import {
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonSearchableSelect,
    Spinner,
    lemonToast,
    Tooltip,
} from '@posthog/lemon-ui'

import api, { ApiConfig, ApiError } from 'lib/api'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { clearLogicReference, initModel } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { slugify } from 'lib/utils/strings'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { parseQueryTablesAndColumns, queryUsesFiltersPlaceholder } from 'scenes/data-warehouse/editor/sql-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import {
    compileNodeBuilder,
    nodeOpensInBuilder,
} from '~/queries/nodes/DataVisualization/insightBuilder/builderNodeConsistency'
import { detectSelectAllTarget } from '~/queries/nodes/DataVisualization/insightBuilder/compileBuilderQuery'
import { performQuery, queryExportContext } from '~/queries/query'
import {
    DataTableNode,
    DataVisualizationNode,
    DatabaseSchemaViewTable,
    HogLanguage,
    HogQLFilters,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLQuery,
    InsightBuilderConfig,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    AccessControlResourceType,
    ChartDisplayType,
    DataModelingEdge,
    DataModelingNode,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDraft,
    ExportContext,
    ExternalDataSource,
    QueryBasedInsightModel,
} from '~/types'

import { validateMetricName } from 'products/data_catalog/frontend/common'
import {
    dataCatalogMetricsCreate,
    dataCatalogMetricsPartialUpdate,
    dataCatalogMetricsRetrieve,
} from 'products/data_catalog/frontend/generated/api'
import { DagSelector, openCreateDagDialog } from 'products/data_modeling/frontend/DagSelector'
import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import { validateEndpointName } from 'products/endpoints/frontend/common'

import type { ExternalDataSourceConnectionOptionApi } from '../../../../../products/warehouse_sources/frontend/generated/api.schemas'
import type { PaginatedResponse } from '../../../lib/api'

// Mirrors MANAGED_WAREHOUSE_SOURCE_PREFIX in products/warehouse_sources/backend/models/external_data_source.py.
export const MANAGED_WAREHOUSE_SOURCE_PREFIX = 'managed_warehouse'
import type { FeatureFlagsSet } from '../../../lib/logic/featureFlagLogic'
import type { DatabaseSchemaQueryResponse, Node } from '../../../queries/schema/schema-general'
import type { DataModelingDAG, DataWarehouseSavedQueryFolder, UserType } from '../../../types'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { validateSavedQueryName } from '../saved_queries/savedQueryNameValidation'
import { dataModelingLogic } from '../scene/dataModelingLogic'
import { BIEditorState, parseBIEditorState } from './bi/biEditorTypes'
import { connectionSelectorLogic } from './connectionSelectorLogic'
import { draftsLogic } from './draftsLogic'
import { fixSQLErrorsLogic } from './fixSQLErrorsLogic'
import type { Response } from './fixSQLErrorsLogic'
import { findInnermostSelectAtOffset, findQueryAtCursor, type QueryRange, splitQueries } from './multiQueryUtils'
import { OutputTab, outputPaneLogic } from './outputPaneLogic'
import { resolveSaveCandidates as resolveSaveCandidatesPure, SaveTargetCycler } from './SaveTargetCycler'
import { SQLEditorMode, isEmbeddedSQLEditorMode } from './sqlEditorModes'
import {
    aiSuggestionOnAccept,
    aiSuggestionOnAcceptText,
    aiSuggestionOnReject,
    aiSuggestionOnRejectText,
} from './suggestions/aiSuggestion'
import {
    queryHistorySuggestionOnAccept,
    queryHistorySuggestionOnAcceptText,
    queryHistorySuggestionOnReject,
    queryHistorySuggestionOnRejectText,
} from './suggestions/queryHistorySuggestion'
import { ViewEmptyState } from './ViewLoadingState'

export interface SqlEditorLogicProps {
    tabId: string
    mode?: SQLEditorMode
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

// Position the active-query outline overlay around `range` in viewport coords.
// Monaco renders inline decorations per-line, so we can't get a single rectangular
// border from a className. Instead, we maintain an absolutely-positioned `div`
// inside the editor's overlay layer and recompute its bounding box from the pixel
// positions of the range's start/end on each line.
export function renderQueryOutline(
    editorInstance: editor.IStandaloneCodeEditor,
    node: HTMLElement,
    range: IRange
): void {
    const model = editorInstance.getModel()
    if (!model) {
        node.style.display = 'none'
        return
    }

    let minLeft = Infinity
    let maxRight = -Infinity
    let minTop = Infinity
    let maxBottom = -Infinity

    // The cached range can outlive the document it was computed against: a paste or edit
    // that removes lines shrinks the model, but this render path runs on scroll/layout
    // without re-clamping. Passing an out-of-range line to `getLineMaxColumn` throws
    // "Illegal value for lineNumber", so clamp every line/column against the live model.
    const lineCount = model.getLineCount()
    const startLine = Math.max(1, Math.min(range.startLineNumber, lineCount))
    const endLine = Math.max(1, Math.min(range.endLineNumber, lineCount))

    for (let line = startLine; line <= endLine; line++) {
        const lineMaxColumn = model.getLineMaxColumn(line)
        const leftCol = Math.min(line === startLine ? range.startColumn : 1, lineMaxColumn)
        const rightCol = line === endLine ? Math.min(range.endColumn, lineMaxColumn) : lineMaxColumn
        if (leftCol >= rightCol) {
            continue
        }
        const startVis = editorInstance.getScrolledVisiblePosition({ lineNumber: line, column: leftCol })
        const endVis = editorInstance.getScrolledVisiblePosition({ lineNumber: line, column: rightCol })
        if (!startVis || !endVis) {
            continue
        }
        if (startVis.left < minLeft) {
            minLeft = startVis.left
        }
        if (endVis.left > maxRight) {
            maxRight = endVis.left
        }
        if (startVis.top < minTop) {
            minTop = startVis.top
        }
        // With wordWrap on, a single model line can span multiple visual rows: `endVis`
        // sits on a later row than `startVis`. Take the max bottom of both so the outline
        // covers the wrapped tail. Width on wrapped lines is still approximate — the
        // mid-rows could extend past either anchor — but the bottom must be correct or
        // wrapped queries get clipped vertically.
        const startBottom = startVis.top + startVis.height
        const endBottom = endVis.top + endVis.height
        if (startBottom > maxBottom) {
            maxBottom = startBottom
        }
        if (endBottom > maxBottom) {
            maxBottom = endBottom
        }
    }

    if (minLeft === Infinity) {
        node.style.display = 'none'
        return
    }

    // Small padding so the border doesn't touch the glyphs / cursor caret.
    const padX = 3
    const padY = 1
    node.style.display = 'block'
    node.style.left = `${minLeft - padX}px`
    node.style.top = `${minTop - padY}px`
    node.style.width = `${maxRight - minLeft + padX * 2}px`
    node.style.height = `${maxBottom - minTop + padY * 2}px`
}

function clearQueryOutlineOverlay(
    cache: sqlEditorLogicType['cache'],
    fallbackEditor?: editor.IStandaloneCodeEditor | null
): void {
    cache.scrollDisposable?.dispose()
    cache.scrollDisposable = null
    cache.layoutDisposable?.dispose()
    cache.layoutDisposable = null

    if (cache.queryOutlineWidget) {
        try {
            ;(cache.queryOutlineEditor ?? fallbackEditor)?.removeOverlayWidget(cache.queryOutlineWidget)
        } catch (e) {
            console.warn('[sqlEditorLogic] failed to remove outline overlay widget', e)
        }
    }

    cache.queryOutlineWidget = null
    cache.queryOutlineEditor = null
    cache.queryOutlineNode = null
    cache.queryOutlineRange = null
    cache.updateQueryOutline = null
}

export const NEW_QUERY = 'Untitled'

// The tab title for an insight. AI-created insights often have only a derived_name — falling
// back to NEW_QUERY would surface as "Untitled" and, worse, get written back as the insight's
// name on the next update. An explicit empty-string name is preserved (`??`, not `||`).
export function insightTabName(insight: QueryBasedInsightModel): string {
    return insight.name ?? insight.derived_name ?? NEW_QUERY
}

export interface QueryTab {
    /** The tab's Monaco model URI — absent until Monaco mounts (see createTab / initialize). */
    uri?: Uri
    view?: DataWarehouseSavedQuery
    name: string
    description?: string
    sourceQuery?: DataVisualizationNode
    insight?: QueryBasedInsightModel
    /**
     * One-shot hosting decision made when an insight opens into the tab: does the insight builder
     * host it? Decided from the saved node's content alone (builder config present and still
     * describing the SQL — never the feature flag) and fixed for the tab's life, so mid-session
     * SQL edits can never flip the layout between builder and classic. Only meaningful while
     * `insight` is set; non-insight tabs derive hosting from the creation flag instead.
     */
    builderHosted?: boolean
    response?: Record<string, any>
    draft?: DataWarehouseSavedQueryDraft
    metricName?: string
    biEditorState?: BIEditorState
}

export type SqlEditorSource = 'insight' | 'endpoint' | 'view' | 'metric'

export interface DataWarehouseAccessControlModalProps {
    resource:
        | AccessControlResourceType.WarehouseTable
        | AccessControlResourceType.WarehouseView
        | AccessControlResourceType.ExternalDataSource
    resourceId: string
    name: string
}

export interface SuggestionPayload {
    suggestedValue?: string
    originalValue?: string
    acceptText?: string
    rejectText?: string
    diffShowRunButton?: boolean
    source?: 'max_ai' | 'hogql_fixer' | 'query_history' | 'materialization_fix'
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

type LegacyDataVisualizationNode = DataVisualizationNode & {
    connectionId?: string
}

function hasOwnProperty(object: Record<string, any>, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(object, key)
}

export function normalizeFiltersForUrl(filters: HogQLFilters | null | undefined): HogQLFilters | undefined {
    const normalizedFilters: HogQLFilters = {}

    if (filters?.properties?.length) {
        normalizedFilters.properties = filters.properties
    }

    if (filters?.dateRange?.date_from || filters?.dateRange?.date_to) {
        normalizedFilters.dateRange = filters.dateRange
    }

    if (filters?.filterTestAccounts) {
        normalizedFilters.filterTestAccounts = true
    }

    return Object.keys(normalizedFilters).length ? normalizedFilters : undefined
}

function parseFiltersFromUrl(filters: unknown): HogQLFilters | undefined {
    if (!filters || typeof filters !== 'object' || Array.isArray(filters)) {
        return undefined
    }

    return normalizeFiltersForUrl(filters as HogQLFilters)
}

export function normalizeRawQuerySource(source: HogQLQuery): HogQLQuery {
    return {
        ...source,
        sendRawQuery: source.connectionId ? source.sendRawQuery || undefined : undefined,
    }
}

export function sanitizeSourceQuery(sourceQuery: DataVisualizationNode): DataVisualizationNode {
    const { connectionId: _ignoredConnectionId, ...sanitizedSourceQuery } = sourceQuery as LegacyDataVisualizationNode

    return {
        ...sanitizedSourceQuery,
        source: normalizeRawQuerySource(sourceQuery.source),
    }
}

export function toDataVisualizationNode(
    query: QueryBasedInsightModel['query'] | null | undefined
): DataVisualizationNode | undefined {
    if (!query) {
        return undefined
    }
    if (query.kind === NodeKind.DataVisualizationNode) {
        // A hand-crafted open_query URL can carry a node with no source; only adopt it when the HogQL source is present
        const source = (query as DataVisualizationNode).source
        return source?.kind === NodeKind.HogQLQuery ? (query as DataVisualizationNode) : undefined
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

export function getCurrentVisualizationQuery(
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
    if (connectionId) {
        hash['c'] = connectionId
        if (values.sourceQuery?.source.sendRawQuery) {
            hash['raw'] = '1'
        }
    }
    const filters = normalizeFiltersForUrl(values.sourceQuery?.source.filters)
    if (filters) {
        hash['filters'] = filters
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
    if (values.activeTab?.biEditorState) {
        hash['mode'] = values.activeTab.biEditorState.editorView
        hash['bi'] = values.activeTab.biEditorState.config
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

// The Monaco model URI string for a tab's editor content. QueryWindow binds the editor to
// this `path` and createTab creates the model at it — they must agree, so both derive it here.
export function tabModelPath(tabId: string): string {
    return `tab-${tabId}`
}

// Apply `text` to the tab's persistent Monaco model as a single undoable edit. The model is
// kept alive across the diff <-> editor swap by `keepCurrentModel` (see QueryWindow), so its
// full undo history survives — pushEditOperations adds one more undoable step rather than
// wiping the stack. This also keeps the editor content in sync after accepting/rejecting a
// suggestion: @monaco-editor/react reuses the existing model on remount without re-applying
// the `value` prop, so the content has to be written onto the model directly. No-ops when the
// editor isn't mounted yet or the content already matches.
function applyUndoableModelEdit(monaco: Monaco | null | undefined, uri: Uri | undefined, text: string): void {
    if (!monaco || !uri) {
        return
    }
    const model = monaco.editor.getModel(uri)
    if (!model || model.getValue() === text) {
        return
    }
    model.pushStackElement()
    model.pushEditOperations([], [{ range: model.getFullModelRange(), text }], () => null)
    model.pushStackElement()
}

const LazyQuery = lazyWithRetry(() =>
    import('~/queries/Query/Query').then((m) => ({ default: m.Query<DataVisualizationNode> }))
)

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sqlEditorLogicValues {
    connectionOptions: ExternalDataSourceConnectionOptionApi[] | null // connectionSelectorLogic
    dags: DataModelingDAG[] // dataModelingLogic
    selectedDagId: string | null // dataModelingLogic
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery> // dataWarehouseViewsLogic
    database: Required<DatabaseSchemaQueryResponse> | null // databaseTableListLogic
    databaseConnectionId: string | null // databaseTableListLogic
    databaseLoading: boolean // databaseTableListLogic
    drafts: DataWarehouseSavedQueryDraft[] // draftsLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    outputActiveTab: OutputTab // outputPaneLogic
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null // sourcesDataLogic
    user: UserType | null // userLogic
    acceptText: string
    accessControlModalOpen: boolean
    activeQueryOffset: number
    activeQueryText: string | null
    activeTab: QueryTab | null
    baseDataLogicKey: string
    baseExportContext: ExportContext | undefined
    basePreviewSource: HogQLQuery | null
    changesToSave: boolean
    currentDraft: DataWarehouseSavedQueryDraft | null | undefined
    dashboardId: number | null
    dataLogicKey: string
    diffShowRunButton: boolean | undefined
    editingAccessControlObject: DataWarehouseAccessControlModalProps | null
    editingInsight: QueryBasedInsightModel | null
    editingMetricName: string | null
    editingView: DataWarehouseSavedQuery | undefined
    editorKey: string
    editorSource: SqlEditorSource
    error: string | null
    exportContext: ExportContext
    finishedLoading: boolean
    fixErrorsError: string | null
    hasFiltersPlaceholder: boolean
    hasQueryInput: boolean
    hoveredNode: string | null
    inProgressDraftEdits: Record<string, string>
    inProgressViewEdits: Record<string, string>
    insightBuilderHosted: boolean
    insightLoading: boolean
    isDraft: boolean
    isEditingMaterializedView: boolean
    isEmbeddedMode: boolean
    isMultiQuery: boolean
    isSourceQueryLastRun: boolean
    lastRunQuery: DataVisualizationNode | null
    materializationModalOpen: boolean
    materializationModalView: DataWarehouseSavedQuery | null
    metadata: HogQLMetadataResponse | null
    metadataLoading: boolean
    metricUpdating: boolean
    originalQueryInput: string | null | undefined
    queryInput: string | null
    rejectText: string
    selectedConnectionId: string | undefined
    selectedConnectionSupportsHogQL: boolean
    selectedDirectSource: ExternalDataSource | undefined
    selectedQueryColumns: Record<string, boolean>
    selectedQueryTablesAndColumns: Record<string, Record<string, boolean>>
    sendRawQueryEnabled: boolean
    sourceQuery: DataVisualizationNode
    splitQueryRanges: QueryRange[]
    suggestedQueryInput: string
    suggestedSource: 'hogql_fixer' | 'materialization_fix' | 'max_ai' | 'query_history' | null
    suggestionPayload: SuggestionPayload | null
    upstream: {
        edges: DataModelingEdge[]
        nodes: DataModelingNode[]
    } | null
    upstreamLoading: boolean
    upstreamViewMode: 'graph' | 'table'
    viewLoading: boolean
    viewQueryLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sqlEditorLogicActions {
    loadConnectionOptionsSuccess: (
        connectionOptions: ExternalDataSourceConnectionOptionApi[],
        payload?: any
    ) => {
        connectionOptions: ExternalDataSourceConnectionOptionApi[]
        payload?: any
    } // connectionSelectorLogic
    maybeLoadConnectionOptions: () => {
        value: true
    } // connectionSelectorLogic
    createDataWarehouseSavedQuerySuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
        payload?:
            | (Partial<DataWarehouseSavedQuery> & {
                  dag_id?: string
                  folder_id?: string | null
                  types: string[][]
              })
            | undefined
    ) => {
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
        payload?: Partial<DataWarehouseSavedQuery> & {
            dag_id?: string
            folder_id?: string | null
            types: string[][]
        }
    } // dataWarehouseViewsLogic
    deleteDataWarehouseSavedQuerySuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
        payload?: string | undefined
    ) => {
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
        payload?: string
    } // dataWarehouseViewsLogic
    loadDataWarehouseSavedQueriesSuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
        payload?: any
    ) => {
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
        payload?: any
    } // dataWarehouseViewsLogic
    loadDataWarehouseSavedQueryFolders: () => any // dataWarehouseViewsLogic
    materializeDataWarehouseSavedQuery: (viewId: string) => {
        viewId: string
    } // dataWarehouseViewsLogic
    runDataWarehouseSavedQuery: (viewId: string) => {
        viewId: string
    } // dataWarehouseViewsLogic
    updateDataWarehouseSavedQuery: (
        view: Partial<DataWarehouseSavedQuery> & {
            edited_history_id?: string
            folder_id?: string | null
            id: string
            lifecycle?: string
            shouldRematerialize?: boolean
            soft_update?: boolean
            sync_frequency?: string
            types?: string[][]
        }
    ) => Partial<DataWarehouseSavedQuery> & {
        edited_history_id?: string
        folder_id?: string | null
        id: string
        lifecycle?: string
        shouldRematerialize?: boolean
        soft_update?: boolean
        sync_frequency?: string
        types?: string[][]
    } // dataWarehouseViewsLogic
    updateDataWarehouseSavedQueryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // dataWarehouseViewsLogic
    updateDataWarehouseSavedQuerySuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
        payload?:
            | (Partial<DataWarehouseSavedQuery> & {
                  edited_history_id?: string
                  folder_id?: string | null
                  id: string
                  lifecycle?: string
                  shouldRematerialize?: boolean
                  soft_update?: boolean
                  sync_frequency?: string
                  types?: string[][]
              })
            | undefined
    ) => {
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
        payload?: Partial<DataWarehouseSavedQuery> & {
            edited_history_id?: string
            folder_id?: string | null
            id: string
            lifecycle?: string
            shouldRematerialize?: boolean
            soft_update?: boolean
            sync_frequency?: string
            types?: string[][]
        }
    } // dataWarehouseViewsLogic
    loadDatabase: (
        args_0?:
            | {
                  force?: boolean
              }
            | undefined
    ) => {
        force?: boolean
    } // databaseTableListLogic
    resetConnectionScope: () => {
        value: true
    } // databaseTableListLogic
    setConnection: (connectionId: string | null) => {
        connectionId: string | null
    } // databaseTableListLogic
    deleteDraft: (
        draftId: string,
        viewName?: string | undefined
    ) => {
        draftId: string
        viewName: string | undefined
    } // draftsLogic
    deleteDraftSuccess: (
        draftId: string,
        viewName?: string | undefined
    ) => {
        draftId: string
        viewName: string | undefined
    } // draftsLogic
    saveAsDraft: (
        query: HogQLQuery,
        viewId: string,
        tab: QueryTab
    ) => {
        query: HogQLQuery
        tab: QueryTab
        viewId: string
    } // draftsLogic
    saveAsDraftSuccess: (
        draft: DataWarehouseSavedQueryDraft,
        tab: QueryTab
    ) => {
        draft: DataWarehouseSavedQueryDraft
        tab: QueryTab
    } // draftsLogic
    fixErrors: (
        query: string,
        error?: string | undefined
    ) => {
        error: string | undefined
        query: string
    } // fixSQLErrorsLogic
    fixErrorsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // fixSQLErrorsLogic
    fixErrorsSuccess: (
        response: Response,
        payload?:
            | {
                  error: string | undefined
                  query: string
              }
            | undefined
    ) => {
        payload?: {
            error: string | undefined
            query: string
        }
        response: Response
    } // fixSQLErrorsLogic
    setActiveTab: (tab: OutputTab) => {
        tab: OutputTab
    } // outputPaneLogic
    _setSuggestionPayload: (payload: SuggestionPayload | null) => {
        payload: SuggestionPayload | null
    }
    closeAccessControlModal: () => {
        value: true
    }
    closeEditingObject: () => {
        value: true
    }
    closeMaterializationModal: () => {
        value: true
    }
    createTab: (
        query?: string,
        view?: DataWarehouseSavedQuery,
        insight?: QueryBasedInsightModel,
        draft?: DataWarehouseSavedQueryDraft,
        metricName?: string,
        biEditorState?: BIEditorState
    ) => {
        biEditorState: BIEditorState | undefined
        draft: DataWarehouseSavedQueryDraft | undefined
        insight: QueryBasedInsightModel<Node<Record<string, any>>> | undefined
        metricName: string | undefined
        query: string | undefined
        view: DataWarehouseSavedQuery | undefined
    }
    deleteInProgressDraftEdit: (draftId: string) => {
        draftId: string
    }
    deleteInProgressViewEdit: (viewId: string) => {
        viewId: string
    }
    editInsight: (
        query: string,
        insight: QueryBasedInsightModel,
        biEditorState?: BIEditorState
    ) => {
        biEditorState: BIEditorState | undefined
        insight: QueryBasedInsightModel<Node<Record<string, any>>>
        query: string
    }
    editView: (
        query: string,
        view: DataWarehouseSavedQuery,
        biEditorState?: BIEditorState
    ) => {
        biEditorState: BIEditorState | undefined
        query: string
        view: DataWarehouseSavedQuery
    }
    enforceConnectionRawQueryMode: () => {
        value: true
    }
    ensureBasePreview: (force?: boolean) => {
        force: boolean | undefined
    }
    initialize: () => {
        value: true
    }
    insertTextAtCursor: (text: string) => {
        text: string
    }
    loadUpstream: (modelId: string) => {
        modelId: string
    }
    loadUpstreamFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadUpstreamSuccess: (
        upstream: {
            edges: DataModelingEdge[]
            nodes: DataModelingNode[]
        },
        payload?: {
            modelId: string
        }
    ) => {
        upstream: {
            edges: DataModelingEdge[]
            nodes: DataModelingNode[]
        }
        payload?: {
            modelId: string
        }
    }
    onAcceptSuggestedQueryInput: (shouldRunQuery?: boolean) => {
        shouldRunQuery: boolean | undefined
    }
    onRejectSuggestedQueryInput: () => {
        value: true
    }
    openAccessControlModal: (editingAccessControlObject: DataWarehouseAccessControlModalProps) => {
        editingAccessControlObject: DataWarehouseAccessControlModalProps
    }
    openMaterializationModal: (view?: DataWarehouseSavedQuery) => {
        view: DataWarehouseSavedQuery | undefined
    }
    reportAIQueryAccepted: () => {
        value: true
    }
    reportAIQueryPromptOpen: () => {
        value: true
    }
    reportAIQueryPrompted: () => {
        value: true
    }
    reportAIQueryRejected: () => {
        value: true
    }
    reviewViewUpdate: (
        view: UpdateViewPayload,
        draftId?: string
    ) => {
        draftId: string | undefined
        view: UpdateViewPayload
    }
    runQuery: (
        queryOverride?: string,
        switchTab?: boolean,
        refreshMode?: 'async' | 'force_async'
    ) => {
        queryOverride: string | undefined
        refreshMode: 'async' | 'force_async' | undefined
        switchTab: boolean | undefined
    }
    runSubquery: () => {
        value: true
    }
    saveAsEndpoint: () => {
        value: true
    }
    saveAsEndpointSubmit: (
        name: string,
        description?: string,
        queryOverride?: string,
        dagId?: string
    ) => {
        dagId: string | undefined
        description: string | undefined
        name: string
        queryOverride: string | undefined
    }
    saveAsInsight: () => {
        value: true
    }
    saveAsInsightSubmit: (
        name: string,
        queryOverride?: string
    ) => {
        name: string
        queryOverride: string | undefined
    }
    saveAsMetric: () => {
        value: true
    }
    saveAsMetricSubmit: (
        name: string,
        description: string,
        queryOverride?: string
    ) => {
        description: string
        name: string
        queryOverride: string | undefined
    }
    saveAsView: (
        materializeAfterSave?: any,
        fromDraft?: string
    ) => {
        fromDraft: string | undefined
        materializeAfterSave: any
    }
    saveAsViewSubmit: (
        name: string,
        materializeAfterSave?: any,
        fromDraft?: string,
        dagId?: string,
        folderId?: string | null,
        isTest?: any,
        queryOverride?: string
    ) => {
        dagId: string | undefined
        folderId: string | null | undefined
        fromDraft: string | undefined
        isTest: any
        materializeAfterSave: any
        name: string
        queryOverride: string | undefined
    }
    saveDraft: (
        activeTab: QueryTab,
        queryInput: string,
        viewId: string
    ) => {
        activeTab: QueryTab
        queryInput: string
        viewId: string
    }
    setActiveQueryText: (
        activeQueryText: string | null,
        activeQueryOffset: number
    ) => {
        activeQueryOffset: number
        activeQueryText: string | null
    }
    setDashboardId: (dashboardId: number | null) => {
        dashboardId: number | null
    }
    setDataError: (error: string | null) => {
        error: string | null
    }
    setEditingInsightDescription: (description: string) => {
        description: string
    }
    setEditingInsightName: (name: string) => {
        name: string
    }
    setEditingMetricName: (metricName: string | null) => {
        metricName: string | null
    }
    setEditorSource: (source: SqlEditorSource) => {
        source: SqlEditorSource
    }
    setError: (error: string | null) => {
        error: string | null
    }
    setFinishedLoading: (loading: boolean) => {
        loading: boolean
    }
    setHoveredNode: (nodeId: string | null) => {
        nodeId: string | null
    }
    setInProgressDraftEdit: (
        draftId: string,
        historyId: string
    ) => {
        draftId: string
        historyId: string
    }
    setInProgressDraftEdits: (inProgressDraftEdits: Record<string, string>) => {
        inProgressDraftEdits: Record<string, string>
    }
    setInProgressViewEdit: (
        viewId: string,
        historyId: string
    ) => {
        historyId: string
        viewId: string
    }
    setInProgressViewEdits: (inProgressViewEdits: Record<string, string>) => {
        inProgressViewEdits: Record<string, string>
    }
    setInsightLoading: (loading: boolean) => {
        loading: boolean
    }
    setLastRunQuery: (lastRunQuery: DataVisualizationNode | null) => {
        lastRunQuery: DataVisualizationNode | null
    }
    setMaterializationModalOpen: (open: boolean) => {
        open: boolean
    }
    setMaterializationModalView: (view: DataWarehouseSavedQuery | null) => {
        view: DataWarehouseSavedQuery | null
    }
    setMetadata: (metadata: HogQLMetadataResponse | null) => {
        metadata: HogQLMetadataResponse | null
    }
    setMetadataLoading: (loading: boolean) => {
        loading: boolean
    }
    setMetricUpdating: (updating: boolean) => {
        updating: boolean
    }
    setQueryInput: (queryInput: string | null) => {
        queryInput: string | null
    }
    setSelectedQueryTablesAndColumns: (tablesAndColumns: Record<string, Record<string, boolean>>) => {
        tablesAndColumns: Record<string, Record<string, boolean>>
    }
    setSendRawQuery: (sendRawQuery: boolean) => {
        sendRawQuery: boolean
    }
    setSourceQuery: (sourceQuery: DataVisualizationNode) => {
        sourceQuery: DataVisualizationNode
    }
    setSuggestedQueryInput: (
        suggestedQueryInput: string,
        source?: SuggestionPayload['source']
    ) => {
        source: 'hogql_fixer' | 'materialization_fix' | 'max_ai' | 'query_history' | undefined
        suggestedQueryInput: string
    }
    setUpstreamViewMode: (mode: 'graph' | 'table') => {
        mode: 'graph' | 'table'
    }
    setViewLoading: (loading: boolean) => {
        loading: boolean
    }
    setViewQueryLoading: (loading: boolean) => {
        loading: boolean
    }
    syncUrlWithQuery: () => {
        value: true
    }
    updateEditingMetric: () => {
        value: true
    }
    updateInsight: () => {
        value: true
    }
    updateTab: (tab: QueryTab) => {
        tab: QueryTab
    }
    updateView: (
        view: UpdateViewPayload,
        draftId?: string
    ) => {
        draftId: string | undefined
        view: UpdateViewPayload
    }
    updateViewSuccess: (
        view: UpdateViewPayload,
        draftId?: string
    ) => {
        draftId: string | undefined
        view: UpdateViewPayload
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sqlEditorLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        suggestedSource: (
            suggestionPayload: SuggestionPayload | null
        ) => 'hogql_fixer' | 'materialization_fix' | 'max_ai' | 'query_history' | null
        diffShowRunButton: (suggestionPayload: SuggestionPayload | null) => boolean | undefined
        acceptText: (suggestionPayload: SuggestionPayload | null) => string
        rejectText: (suggestionPayload: SuggestionPayload | null) => string
        suggestedQueryInput: (suggestionPayload: SuggestionPayload | null, queryInput: string | null) => string
        originalQueryInput: (
            suggestionPayload: SuggestionPayload | null,
            queryInput: string | null
        ) => string | null | undefined
        editingView: (activeTab: QueryTab | null) => DataWarehouseSavedQuery | undefined
        editingMetricName: (activeTab: QueryTab | null) => string | null
        changesToSave: (editingView: DataWarehouseSavedQuery | undefined, queryInput: string | null) => boolean
        exportContext: (sourceQuery: DataVisualizationNode) => ExportContext
        baseDataLogicKey: (dataLogicKey: string) => string
        basePreviewSource: (sourceQuery: DataVisualizationNode) => HogQLQuery | null
        baseExportContext: (basePreviewSource: HogQLQuery | null) => ExportContext | undefined
        selectedConnectionId: (sourceQuery: DataVisualizationNode) => string | undefined
        selectedDirectSource: (
            dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
            selectedConnectionId: string | undefined
        ) => ExternalDataSource | undefined
        sendRawQueryEnabled: (sourceQuery: DataVisualizationNode, selectedConnectionId: string | undefined) => boolean
        selectedConnectionSupportsHogQL: (
            connectionOptions: ExternalDataSourceConnectionOptionApi[] | null,
            selectedConnectionId: string | undefined
        ) => boolean
        isEditingMaterializedView: (editingView: DataWarehouseSavedQuery | undefined) => boolean
        splitQueryRanges: (queryInput: string | null) => QueryRange[]
        isMultiQuery: (splitQueryRanges: QueryRange[]) => boolean
        isSourceQueryLastRun: (
            queryInput: string | null,
            lastRunQuery: DataVisualizationNode | null,
            sourceQuery: DataVisualizationNode,
            splitQueryRanges: QueryRange[],
            insightBuilderHosted: boolean
        ) => boolean
        hasFiltersPlaceholder: (queryInput: string | null) => boolean
        hasQueryInput: (queryInput: string | null) => boolean
        isEmbeddedMode: (arg: SQLEditorMode | undefined) => boolean
        insightBuilderHosted: (
            featureFlags: FeatureFlagsSet,
            isEmbeddedMode: boolean,
            activeTab: QueryTab | null
        ) => boolean
        dataLogicKey: (tabId: string) => string
        isDraft: (activeTab: QueryTab | null) => boolean
        currentDraft: (activeTab: QueryTab | null) => DataWarehouseSavedQueryDraft | null | undefined
        selectedQueryColumns: (
            selectedQueryTablesAndColumns: Record<string, Record<string, boolean>>
        ) => Record<string, boolean>
    }
}

export type sqlEditorLogicType = MakeLogicType<
    sqlEditorLogicValues,
    sqlEditorLogicActions,
    SqlEditorLogicProps,
    sqlEditorLogicMeta
>

// Which mounted editors currently want the shared schema catalog scoped to a connection, keyed by
// tab id. Several editors can be mounted at once (notebook SQL nodes, metrics, endpoints) on the
// same connection, so the last one out is the one that hands the catalog back unscoped.
const connectionScopeOwners = new Map<string, string>()

function claimConnectionScope(tabId: string, connectionId: string | null | undefined): void {
    if (connectionId) {
        connectionScopeOwners.set(tabId, connectionId)
    } else {
        connectionScopeOwners.delete(tabId)
    }
}

// Drops this tab's claim and reports whether the scoped connection is now unclaimed.
function releaseConnectionScope(tabId: string, scopedConnectionId: string | null): boolean {
    connectionScopeOwners.delete(tabId)
    return scopedConnectionId !== null && ![...connectionScopeOwners.values()].includes(scopedConnectionId)
}

export const sqlEditorLogic = kea<sqlEditorLogicType>([
    path(['data-warehouse', 'editor', 'sqlEditorLogic']),
    props({ mode: SQLEditorMode.FullScene } as SqlEditorLogicProps),
    key((props) => props.tabId),
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
            connectionSelectorLogic,
            ['connectionOptions'],
            databaseTableListLogic,
            ['database', 'databaseLoading', 'connectionId as databaseConnectionId'],
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
            fixSQLErrorsLogic,
            ['fixErrors', 'fixErrorsSuccess', 'fixErrorsFailure'],
            draftsLogic,
            ['saveAsDraft', 'deleteDraft', 'saveAsDraftSuccess', 'deleteDraftSuccess'],
            databaseTableListLogic,
            ['setConnection', 'loadDatabase', 'resetConnectionScope'],
            connectionSelectorLogic,
            ['loadConnectionOptionsSuccess', 'maybeLoadConnectionOptions'],
        ],
    })),
    actions(() => ({
        setSelectedQueryTablesAndColumns: (tablesAndColumns: Record<string, Record<string, boolean>>) => ({
            tablesAndColumns,
        }),
        setQueryInput: (queryInput: string | null) => ({ queryInput }),
        setActiveQueryText: (activeQueryText: string | null, activeQueryOffset: number) => ({
            activeQueryText,
            activeQueryOffset,
        }),
        runQuery: (queryOverride?: string, switchTab?: boolean, refreshMode?: 'async' | 'force_async') => ({
            queryOverride,
            switchTab,
            refreshMode,
        }),
        // Load the builder base query's raw rows into the Source tab's own data node
        ensureBasePreview: (force?: boolean) => ({ force }),
        createTab: (
            query?: string,
            view?: DataWarehouseSavedQuery,
            insight?: QueryBasedInsightModel,
            draft?: DataWarehouseSavedQueryDraft,
            metricName?: string,
            biEditorState?: BIEditorState
        ) => ({
            query,
            view,
            insight,
            draft,
            metricName,
            biEditorState,
        }),
        updateTab: (tab: QueryTab) => ({ tab }),

        initialize: true,
        loadUpstream: (modelId: string) => ({ modelId }),
        saveAsView: (materializeAfterSave = false, fromDraft?: string) => ({
            fromDraft,
            materializeAfterSave,
        }),
        saveAsViewSubmit: (
            name: string,

            materializeAfterSave = false,

            fromDraft?: string,

            dagId?: string,
            folderId?: string | null,
            isTest = false,
            queryOverride?: string
        ) => ({
            name,
            materializeAfterSave,
            fromDraft,
            dagId,
            folderId,
            isTest,
            queryOverride,
        }),
        saveAsInsight: true,
        saveAsInsightSubmit: (name: string, queryOverride?: string) => ({
            name,
            queryOverride,
        }),
        saveAsEndpoint: true,
        saveAsEndpointSubmit: (name: string, description?: string, queryOverride?: string, dagId?: string) => ({
            name,
            description,
            queryOverride,
            dagId,
        }),
        saveAsMetric: true,
        saveAsMetricSubmit: (name: string, description: string, queryOverride?: string) => ({
            name,
            description,
            queryOverride,
        }),
        setEditingMetricName: (metricName: string | null) => ({ metricName }),
        updateEditingMetric: true,
        setMetricUpdating: (updating: boolean) => ({ updating }),
        updateInsight: true,
        setEditingInsightName: (name: string) => ({ name }),
        setEditingInsightDescription: (description: string) => ({ description }),
        closeEditingObject: true,
        setFinishedLoading: (loading: boolean) => ({ loading }),
        setError: (error: string | null) => ({ error }),
        setDataError: (error: string | null) => ({ error }),
        setSourceQuery: (sourceQuery: DataVisualizationNode) => ({
            sourceQuery,
        }),
        setMetadata: (metadata: HogQLMetadataResponse | null) => ({ metadata }),
        setMetadataLoading: (loading: boolean) => ({ loading }),
        setInsightLoading: (loading: boolean) => ({ loading }),
        setViewLoading: (loading: boolean) => ({ loading }),
        setViewQueryLoading: (loading: boolean) => ({ loading }),
        setMaterializationModalOpen: (open: boolean) => ({ open }),
        setMaterializationModalView: (view: DataWarehouseSavedQuery | null) => ({ view }),
        editView: (query: string, view: DataWarehouseSavedQuery, biEditorState?: BIEditorState) => ({
            query,
            view,
            biEditorState,
        }),
        editInsight: (query: string, insight: QueryBasedInsightModel, biEditorState?: BIEditorState) => ({
            query,
            insight,
            biEditorState,
        }),
        setLastRunQuery: (lastRunQuery: DataVisualizationNode | null) => ({
            lastRunQuery,
        }),
        _setSuggestionPayload: (payload: SuggestionPayload | null) => ({
            payload,
        }),
        setSuggestedQueryInput: (suggestedQueryInput: string, source?: SuggestionPayload['source']) => ({
            suggestedQueryInput,
            source,
        }),
        onAcceptSuggestedQueryInput: (shouldRunQuery?: boolean) => ({
            shouldRunQuery,
        }),
        onRejectSuggestedQueryInput: true,
        reportAIQueryPrompted: true,
        reportAIQueryAccepted: true,
        reportAIQueryRejected: true,
        reportAIQueryPromptOpen: true,
        setInProgressViewEdit: (viewId: string, historyId: string) => ({
            viewId,
            historyId,
        }),
        setInProgressViewEdits: (inProgressViewEdits: Record<string, string>) => ({
            inProgressViewEdits,
        }),
        deleteInProgressViewEdit: (viewId: string) => ({ viewId }),
        setInProgressDraftEdit: (draftId: string, historyId: string) => ({
            draftId,
            historyId,
        }),
        setInProgressDraftEdits: (inProgressDraftEdits: Record<string, string>) => ({
            inProgressDraftEdits,
        }),
        deleteInProgressDraftEdit: (draftId: string) => ({ draftId }),
        reviewViewUpdate: (view: UpdateViewPayload, draftId?: string) => ({
            view,
            draftId,
        }),
        updateView: (view: UpdateViewPayload, draftId?: string) => ({
            view,
            draftId,
        }),
        updateViewSuccess: (view: UpdateViewPayload, draftId?: string) => ({
            view,
            draftId,
        }),
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
        runSubquery: true,
        setSendRawQuery: (sendRawQuery: boolean) => ({ sendRawQuery }),
        enforceConnectionRawQueryMode: true,
        setDashboardId: (dashboardId: number | null) => ({ dashboardId }),
        openMaterializationModal: (view?: DataWarehouseSavedQuery) => ({
            view,
        }),
        closeMaterializationModal: true,
        openAccessControlModal: (editingAccessControlObject: DataWarehouseAccessControlModalProps) => ({
            editingAccessControlObject,
        }),
        closeAccessControlModal: true,
    })),
    propsChanged(({ actions, props, cache }, oldProps) => {
        if (oldProps.editor && oldProps.editor !== props.editor) {
            clearQueryOutlineOverlay(cache, oldProps.editor)
        }

        if (
            (!oldProps.monaco || !oldProps.editor || oldProps.editor !== props.editor) &&
            props.monaco &&
            props.editor
        ) {
            actions.initialize()

            // Listen for cursor position changes to update the active query highlight.
            // Debounced because each run can fire a HogQLMetadata request for the current
            // subquery, which is too expensive to do on every arrow key.
            cache.cursorDisposable?.dispose()
            cache.cursorDisposable = props.editor.onDidChangeCursorPosition(() => {
                cache.scheduleActiveQueryDecoration?.()
            })

            // Set up the active-query outline overlay. We render a single `div` parented
            // to Monaco's overlay layer (viewport-fixed) and reposition it on scroll/layout.
            const editorInstance = props.editor
            const outlineNode = document.createElement('div')
            outlineNode.className = 'active-query-outline'
            outlineNode.style.position = 'absolute'
            outlineNode.style.display = 'none'
            clearQueryOutlineOverlay(cache, editorInstance)
            const outlineWidget: editor.IOverlayWidget = {
                getId: () => `sql-editor.active-query-outline.${props.tabId || 'default'}`,
                getDomNode: () => outlineNode,
                // Returning `null` keeps the widget unanchored — we drive its position
                // manually via inline `top`/`left` styles set in `renderQueryOutline`.
                getPosition: () => null,
            }
            editorInstance.removeOverlayWidget(outlineWidget)
            editorInstance.addOverlayWidget(outlineWidget)
            cache.queryOutlineWidget = outlineWidget
            cache.queryOutlineEditor = editorInstance
            cache.queryOutlineNode = outlineNode

            cache.updateQueryOutline = (range: IRange | null): void => {
                cache.queryOutlineRange = range
                if (!range) {
                    outlineNode.style.display = 'none'
                    return
                }
                renderQueryOutline(editorInstance, outlineNode, range)
            }

            // Reposition the overlay on scroll and layout/resize. These don't change the
            // range, only its pixel coordinates, so we skip the SQL parsing path entirely.
            cache.scrollDisposable?.dispose()
            cache.scrollDisposable = editorInstance.onDidScrollChange(() => {
                if (cache.queryOutlineRange) {
                    renderQueryOutline(editorInstance, outlineNode, cache.queryOutlineRange)
                }
            })
            cache.layoutDisposable?.dispose()
            cache.layoutDisposable = editorInstance.onDidLayoutChange(() => {
                if (cache.queryOutlineRange) {
                    renderQueryOutline(editorInstance, outlineNode, cache.queryOutlineRange)
                }
            })
        }
    }),
    loaders(() => ({
        upstream: [
            null as { nodes: DataModelingNode[]; edges: DataModelingEdge[] } | null,
            {
                loadUpstream: async (payload: { modelId: string }) => {
                    return await api.dataModelingNodes.lineage({ savedQueryId: payload.modelId })
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
        activeQueryText: [
            null as string | null,
            {
                setActiveQueryText: (_, { activeQueryText }) => activeQueryText,
            },
        ],
        activeQueryOffset: [
            0 as number,
            {
                setActiveQueryText: (_, { activeQueryOffset }) => activeQueryOffset,
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
        accessControlModalOpen: [
            false,
            {
                openAccessControlModal: () => true,
                closeAccessControlModal: () => false,
            },
        ],
        editingAccessControlObject: [
            null as DataWarehouseAccessControlModalProps | null,
            {
                openAccessControlModal: (_, { editingAccessControlObject }) => editingAccessControlObject,
                closeAccessControlModal: () => null,
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
        // Scoped to the editor "open a view" flow so the editor-pane overlay does not flash
        // during the materialization modal's own (also viewLoading-gated) fetch.
        viewQueryLoading: [
            false,
            {
                setViewQueryLoading: (_, { loading }) => loading,
            },
        ],
        insightLoading: [
            false,
            {
                setInsightLoading: (_, { loading }) => loading,
            },
        ],
        metricUpdating: [
            false,
            {
                setMetricUpdating: (_, { updating }) => updating,
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
        // if a view edit starts, store the historyId in the state
        inProgressViewEdits: [
            {} as Record<string, string>,
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
            {} as Record<string, string>,
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
    listeners(({ values, props, actions, asyncActions, cache }) => {
        // Extract cursor offset and selection text from monaco and defer to the pure helper.
        const resolveSaveCandidates = (): ReturnType<typeof resolveSaveCandidatesPure> => {
            const fullText = values.queryInput ?? ''
            const editorInstance = props.editor
            let cursorOffset: number | null = null
            let selectionText: string | null = null

            if (editorInstance) {
                const model = editorInstance.getModel()
                const selection = editorInstance.getSelection()
                if (model && selection && !selection.isEmpty()) {
                    selectionText = model.getValueInRange(selection)
                }
                const position = editorInstance.getPosition()
                if (model && position) {
                    cursorOffset = model.getOffsetAt(position)
                }
            }

            return resolveSaveCandidatesPure(fullText, cursorOffset, selectionText)
        }

        return {
            fixErrorsSuccess: ({ response }) => {
                actions.setSuggestedQueryInput(response.query, 'hogql_fixer')

                posthog.capture('ai-error-fixer-success', {
                    trace_id: response.trace_id,
                })
            },
            fixErrorsFailure: () => {
                posthog.capture('ai-error-fixer-failure')
            },
            reportAIQueryPrompted: () => {
                posthog.capture('ai_query_prompted')
            },
            reportAIQueryAccepted: () => {
                posthog.capture('ai_query_accepted')
            },
            reportAIQueryRejected: () => {
                posthog.capture('ai_query_rejected')
            },
            reportAIQueryPromptOpen: () => {
                posthog.capture('ai_query_prompt_open')
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
            setSuggestedQueryInput: ({ suggestedQueryInput, source }) => {
                // If there's no active tab, create one first to ensure Monaco Editor is available.
                // Embedded mode has no tabs at all — falling into createTab would replace the query
                // outright instead of showing the accept/reject diff.
                if (!values.activeTab && !values.isEmbeddedMode) {
                    actions.createTab(suggestedQueryInput)
                    return
                }

                const isQueryHistory = source === 'query_history'
                if (isQueryHistory) {
                    // Accept/cancel of the restore is captured via sql-editor-accepted/rejected-suggestion
                    posthog.capture('sql-editor-history-restore-initiated')
                }

                // Always create suggestion payload when a new suggestion comes in, even for consecutive suggestions
                // Only skip diff mode if the editor is completely empty
                if (values.queryInput && values.queryInput.trim() !== '') {
                    actions._setSuggestionPayload({
                        suggestedValue: suggestedQueryInput,
                        originalValue: values.queryInput, // Store the current content as original for diff mode
                        acceptText: isQueryHistory ? queryHistorySuggestionOnAcceptText : aiSuggestionOnAcceptText,
                        rejectText: isQueryHistory ? queryHistorySuggestionOnRejectText : aiSuggestionOnRejectText,
                        onAccept: isQueryHistory ? queryHistorySuggestionOnAccept : aiSuggestionOnAccept,
                        onReject: isQueryHistory ? queryHistorySuggestionOnReject : aiSuggestionOnReject,
                        source,
                        diffShowRunButton: true,
                    })
                } else {
                    actions.setQueryInput(suggestedQueryInput)
                }
            },
            onAcceptSuggestedQueryInput: ({ shouldRunQuery }) => {
                values.suggestionPayload?.onAccept(!!shouldRunQuery, actions, values, props)

                // Write the accepted query onto the tab's persistent model as one undoable
                // edit. The model survives the diff <-> editor swap (keepCurrentModel), so its
                // existing undo history is preserved and cmd+z walks back through the accepted
                // query to the pre-AI query and the rest of the edit history.
                applyUndoableModelEdit(props.monaco, values.activeTab?.uri, values.queryInput ?? '')

                posthog.capture('sql-editor-accepted-suggestion', {
                    source: values.suggestedSource,
                })
                actions._setSuggestionPayload(null)
            },
            onRejectSuggestedQueryInput: () => {
                values.suggestionPayload?.onReject(actions, values, props)

                // Keep the persistent model's content in sync with the reverted query (the
                // suggestion was shown in a throwaway diff model, not this one). This is a
                // no-op when the model already matches, so rejecting adds no undo step.
                applyUndoableModelEdit(props.monaco, values.activeTab?.uri, values.queryInput ?? '')

                posthog.capture('sql-editor-rejected-suggestion', {
                    source: values.suggestedSource,
                })
                actions._setSuggestionPayload(null)
            },
            editView: ({ query, view, biEditorState }) => {
                actions.createTab(query, view, undefined, undefined, undefined, biEditorState)
            },
            editInsight: ({ query, insight, biEditorState }) => {
                actions.createTab(query, undefined, insight, undefined, undefined, biEditorState)
            },
            createTab: async ({ query = '', view, insight, draft, metricName, biEditorState }) => {
                // Use tabId to ensure each browser tab has its own unique Monaco model
                const tabName = insight ? insightTabName(insight) : draft?.name || view?.name || NEW_QUERY
                const tabDescription = insight?.description ?? ''
                const rawInsightVisualizationQuery = toDataVisualizationNode(insight?.query)
                const insightVisualizationQuery = rawInsightVisualizationQuery
                    ? sanitizeSourceQuery(rawInsightVisualizationQuery)
                    : undefined

                // One-shot hosting decision for insight opens, mirrored by the open_insight gate:
                // a builder config that still describes the SQL opens in the builder for everyone
                // (the flag only gates creating new builder insights). A stale config — SQL edited
                // outside the builder — opens classic: the SQL wins.
                const opensInBuilder = nodeOpensInBuilder(insightVisualizationQuery)

                // What the buffer should hold for the object being opened. Builder-hosted insights
                // put the base SQL in the buffer (runs go through the compiled text); classic ones
                // edit the compiled SQL directly. A bare createTab() resets the buffer to a blank
                // query.
                const nextBufferText: string = query
                    ? query
                    : draft
                      ? draft.query.query
                      : view
                        ? (view.query?.query ?? '')
                        : insightVisualizationQuery
                          ? opensInBuilder
                              ? insightVisualizationQuery.builder!.baseQuery
                              : insightVisualizationQuery.source.query || ''
                          : query

                // The Monaco model is a pre-creation optimization (the editor also creates it from
                // its `path` binding on mount), but the tab's identity — insight, view, name — must
                // never depend on Monaco being mounted, or opening an insight before the editor
                // loads silently drops it and the save flow forks a duplicate.
                let uri: Uri | undefined
                if (props.monaco) {
                    uri = props.monaco.Uri.parse(tabModelPath(props.tabId))
                    let model = props.monaco.editor.getModel(uri)
                    if (!model) {
                        model = props.monaco.editor.createModel(nextBufferText, 'hogQL', uri)
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
                    } else if (model.getValue() !== nextBufferText) {
                        // The browser tab reuses one model across opened objects. When the query
                        // pane is hidden (Visualization tab) the model can't sync from the buffer
                        // state, so switching insights would otherwise show the previous object's
                        // SQL on the next Source visit.
                        model.setValue(nextBufferText)
                    }
                }

                actions.updateTab({
                    uri,
                    view,
                    insight,
                    builderHosted: insight ? opensInBuilder : undefined,
                    name: tabName,
                    description: tabDescription,
                    sourceQuery: insightVisualizationQuery,
                    draft: draft,
                    metricName,
                    biEditorState,
                })
                if (insightVisualizationQuery) {
                    actions.setLastRunQuery(insightVisualizationQuery)
                }
                actions.setQueryInput(nextBufferText)

                // Opening another query can replace sourceQuery without changing the connection,
                // so the selectedConnectionId subscription does not run again.
                actions.enforceConnectionRawQueryMode()

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
                actions.ensureBasePreview()
            },
            // Opening the Source tab on a builder tab shows the base query's raw rows
            setActiveTab: ({ tab }) => {
                if (tab === OutputTab.Results) {
                    actions.ensureBasePreview()
                }
            },
            ensureBasePreview: async ({ force }, breakpoint) => {
                if (!values.insightBuilderHosted) {
                    return
                }
                // Let a forced tab switch from the insight-open flow land before deciding
                await breakpoint(10)
                if (values.outputActiveTab !== OutputTab.Results) {
                    return
                }
                const baseSource = values.basePreviewSource
                if (!baseSource) {
                    return
                }
                // Tag only the executed query so saved insights never pick tags up
                const executedSource: HogQLQuery = {
                    ...baseSource,
                    tags: { ...baseSource.tags, productKey: 'sql_editor' },
                }
                const baseNodeLogic = dataNodeLogic({
                    key: values.baseDataLogicKey,
                    query: executedSource,
                    // autoLoad defaults to true with a blocking load on mount — this node loads
                    // only through the explicit loadData below
                    autoLoad: false,
                    dataNodeCollectionId: values.baseDataLogicKey,
                })
                if (!cache.umountBaseDataNode) {
                    cache.umountBaseDataNode = baseNodeLogic.mount()
                }
                if (!force && cache.lastBasePreviewText === baseSource.query && baseNodeLogic.values.response) {
                    return
                }
                cache.lastBasePreviewText = baseSource.query
                baseNodeLogic.actions.loadData(force ? 'force_async' : 'async', undefined, executedSource)
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
            enforceConnectionRawQueryMode: () => {
                // Raw-only connections cannot compile HogQL — force raw SQL mode.
                // The managed warehouse (auto-provisioned Duckgres) speaks DuckDB
                // natively end-to-end, so raw mode is the better default for it too:
                // it skips the HogQL reprint and reaches the engine verbatim.
                if (values.selectedConnectionId && !values.sourceQuery.source.sendRawQuery) {
                    const option = (values.connectionOptions ?? []).find(
                        (option) => option.id === values.selectedConnectionId
                    )
                    const isManagedWarehouseSource =
                        option?.prefix === MANAGED_WAREHOUSE_SOURCE_PREFIX && option?.source_type === 'Postgres'

                    if (!values.selectedConnectionSupportsHogQL || isManagedWarehouseSource) {
                        actions.setSendRawQuery(true)
                    }
                }
            },
            // Options can load after a connection was restored from the URL.
            loadConnectionOptionsSuccess: () => {
                actions.enforceConnectionRawQueryMode()
            },
            runSubquery: async () => {
                if (!props.editor) {
                    actions.runQuery()
                    return
                }
                const model = props.editor.getModel()
                const position = props.editor.getPosition()
                if (!model || !position) {
                    actions.runQuery()
                    return
                }

                const fullText = values.queryInput ?? ''
                const queries = splitQueries(fullText)
                const cursorOffset = model.getOffsetAt(position)
                const activeQuery = findQueryAtCursor(queries, cursorOffset)

                if (!activeQuery) {
                    actions.runQuery()
                    return
                }

                const subquery = await findInnermostSelectAtOffset(activeQuery.query, cursorOffset, activeQuery.start)

                const rangeToRun = subquery ?? activeQuery

                // Flash highlight on the subquery/query about to run
                const startPos = model.getPositionAt(rangeToRun.start)
                const endPos = model.getPositionAt(rangeToRun.end)
                cache.activeQueryDecorationIds = props.editor.deltaDecorations(cache.activeQueryDecorationIds ?? [], [
                    {
                        range: {
                            startLineNumber: startPos.lineNumber,
                            startColumn: startPos.column,
                            endLineNumber: endPos.lineNumber,
                            endColumn: endPos.column,
                        },
                        options: {
                            className: 'active-query-highlight-flash',
                        },
                    },
                ])

                // Remove flash after a short delay and restore normal decoration.
                // Track the timeout so we can clear it on unmount (avoids touching a disposed editor).
                if (cache.activeQueryFlashTimeout) {
                    window.clearTimeout(cache.activeQueryFlashTimeout)
                }
                cache.activeQueryFlashTimeout = window.setTimeout(() => {
                    cache.activeQueryFlashTimeout = null
                    cache.updateActiveQueryDecoration?.()
                }, 600)

                actions.runQuery(rangeToRun.query)
            },
            initialize: async () => {
                actions.setFinishedLoading(false)

                // Backfill the tab's Monaco model URI when Monaco arrives after the tab was
                // created (e.g. an insight opened while the query pane was hidden). The editor's
                // `path` binding may have created the model already — reuse it, and only track
                // models this logic created so the disposal contract holds.
                if (props.monaco && values.activeTab && !values.activeTab.uri) {
                    const uri = props.monaco.Uri.parse(tabModelPath(props.tabId))
                    let model = props.monaco.editor.getModel(uri)
                    if (!model) {
                        model = props.monaco.editor.createModel(values.queryInput ?? '', 'hogQL', uri)
                        cache.createdModels = cache.createdModels || []
                        cache.createdModels.push(model)
                        initModel(
                            model,
                            codeEditorLogic({
                                key: `hogql-editor-${props.tabId}`,
                                query: values.sourceQuery?.source.query ?? '',
                                language: 'hogQL',
                            })
                        )
                    }
                    actions.updateTab({ ...values.activeTab, uri })
                }
            },
            setQueryInput: async ({ queryInput }, breakpoint) => {
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
                actions.updateTab({
                    ...tabToUpdate,
                    name: draft.name,
                    draft: draft,
                })
            },
            runQuery: ({ queryOverride, switchTab, refreshMode }) => {
                // A tab is builder-owned only while the builder actually hosts it. A builder
                // insight whose config went stale opens as a plain SQL tab: the buffer holds the
                // compiled SQL and runs must execute (and save) the buffer, not the stored text.
                const builderOwned = values.insightBuilderHosted && !!values.sourceQuery.builder?.enabled

                // Builder tabs: an explicit whole-buffer Run means "this is my new base" — adopt
                // the edited buffer into the builder config and recompile the wells against it,
                // so the run (and the Source grid) reflect what the user just wrote. Only a
                // partial selection is an ad-hoc run. Buffers the builder can't compile against
                // (multiple statements, empty wells) fall through to running the stored insight.
                let adoptedCompiledSql: string | null = null
                if (builderOwned) {
                    const buffer = values.queryInput ?? ''
                    const wholeRun = !queryOverride || queryOverride.trim() === buffer.trim()
                    const builder = values.sourceQuery.builder!
                    if (wholeRun && buffer.trim() && buffer.trim() !== builder.baseQuery.trim()) {
                        const editingView = values.editingView
                        const baseView =
                            detectSelectAllTarget(buffer) ??
                            (editingView && buffer.trim() === (editingView.query?.query ?? '').trim()
                                ? (editingView.name ?? null)
                                : null)
                        const newBuilder: InsightBuilderConfig = {
                            ...builder,
                            baseQuery: buffer,
                            baseView: baseView ?? undefined,
                        }
                        try {
                            const compiled = compileNodeBuilder(newBuilder, values.sourceQuery.display)
                            actions.setSourceQuery({
                                ...values.sourceQuery,
                                // The compiledQuery snapshot must track the recompile: it is what
                                // decides whether the insight reopens in the builder, so leaving
                                // the old one behind would demote the insight to classic on the
                                // next open (and strip the config on the save after that).
                                builder: { ...newBuilder, compiledQuery: compiled.sql },
                                source: { ...values.sourceQuery.source, query: compiled.sql },
                            })
                            adoptedCompiledSql = compiled.sql
                        } catch {
                            // Not a usable base — run the stored insight as before
                        }
                    }
                }

                let query: string
                if (adoptedCompiledSql) {
                    query = adoptedCompiledSql
                } else if (queryOverride) {
                    // Explicit override (e.g. user selected text and pressed Cmd+Enter). On a
                    // builder tab, selecting the whole buffer and running means "run the insight",
                    // exactly like the Run button — only a partial selection is an ad-hoc run.
                    query =
                        builderOwned && queryOverride.trim() === (values.queryInput ?? '').trim()
                            ? values.sourceQuery.source.query
                            : queryOverride
                } else if (builderOwned) {
                    // The builder owns execution while enabled: the Monaco buffer holds the *base*
                    // query, and running it would replace the compiled SQL and orphan the chart
                    // (its settings reference compiled aliases). Run the compiled text.
                    query = values.sourceQuery.source.query
                } else {
                    // No override — find the query under the cursor
                    const fullText = values.queryInput ?? ''
                    const queries = splitQueries(fullText)
                    if (queries.length > 1 && props.editor) {
                        const model = props.editor.getModel()
                        const position = props.editor.getPosition()
                        if (model && position) {
                            const cursorOffset = model.getOffsetAt(position)
                            const match = findQueryAtCursor(queries, cursorOffset)
                            query = match?.query ?? fullText
                        } else {
                            query = fullText
                        }
                    } else {
                        query = fullText
                    }
                }

                const newSource = normalizeRawQuerySource({
                    ...values.sourceQuery.source,
                    query,
                })

                // Tag only the executed query — keeping tags out of sourceQuery so saved
                // insights/views and change detection never pick them up
                const executedSource: HogQLQuery = {
                    ...newSource,
                    tags: { ...newSource.tags, productKey: 'sql_editor' },
                }

                // Builder tabs: source.query is the compiled SQL owned by applyWells — an ad-hoc
                // run (a selection, a subquery) must not overwrite it, or the chart orphans and a
                // subsequent save persists the ad-hoc text as the insight's query. lastRunQuery
                // still records what actually ran, so staleness surfaces and saving stays gated
                // until the insight's own query has run.
                if (!builderOwned || query === values.sourceQuery.source.query) {
                    actions.setSourceQuery({
                        ...values.sourceQuery,
                        source: newSource,
                    })
                }
                actions.setLastRunQuery({
                    ...values.sourceQuery,
                    source: newSource,
                })
                if (!cache.umountDataNode) {
                    cache.umountDataNode = dataNodeLogic({
                        key: values.dataLogicKey,
                        query: executedSource,
                    }).mount()
                }

                // 'async' respects the backend query cache; user-initiated runs force a fresh
                // execution, while programmatic reruns (builder recompiles, tab switches) don't
                dataNodeLogic({
                    key: values.dataLogicKey,
                    query: executedSource,
                }).actions.loadData(refreshMode ?? (!switchTab ? 'force_async' : 'async'), undefined, executedSource)

                // An explicit Run on a builder tab also refreshes the Source tab's raw grid
                if (builderOwned && values.outputActiveTab === OutputTab.Results) {
                    actions.ensureBasePreview(true)
                }

                // Mark the first query task as complete when the query is run
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.RunFirstQuery)
                const compactQuery = query.replace(/\s+/g, ' ').trim()
                const truncated = compactQuery.length > 80 ? compactQuery.slice(0, 77) + '…' : compactQuery
                tryShowMCPHint('sql.execute', truncated ? { derivedPrompt: `Run this SQL: ${truncated}` } : undefined)
            },
            saveAsView: async ({ fromDraft, materializeAfterSave = false }) => {
                const multiDagEnabled = !!values.featureFlags[FEATURE_FLAGS.DATA_MODELING_MULTI_DAG]

                // Ensure DAGs are loaded via dataModelingLogic
                if (multiDagEnabled && values.dags.length === 0) {
                    await dataModelingLogic.asyncActions.loadDags()
                }

                const isStaff = values.user?.is_staff ?? false
                const candidates = resolveSaveCandidates()
                const selectedRef = {
                    current: candidates.queries[candidates.initialIndex],
                }

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
                    showErrorsOnTouch: true,
                    initialValues: {
                        viewName: values.activeTab?.name || '',
                        folderId: null,
                        isTest: false,
                        materializeAfterSave,
                        dagId: multiDagEnabled
                            ? (values.dags.find((d) => d.id === values.selectedDagId)?.id ?? values.dags[0]?.id ?? null)
                            : undefined,
                    },
                    description: `View names must start with a letter, '_', or '$' and can only contain letters, numbers, '_', '.', or '$'. Spaces are not allowed.`,
                    content: (isLoading) =>
                        isLoading ? (
                            <div className="h-[37px] flex items-center">
                                <ViewEmptyState />
                            </div>
                        ) : (
                            <>
                                <LemonField name="viewName" label="Name">
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
                                            <LemonSearchableSelect<string | null>
                                                value={value}
                                                onChange={onChange}
                                                searchPlaceholder="Search folders"
                                                options={[
                                                    ...folderOptions,
                                                    {
                                                        value: '__add_new_folder__',
                                                        label: '+ Add new folder',
                                                        labelInMenu: () => (
                                                            <button
                                                                type="button"
                                                                className="w-full text-left text-primary px-2 py-1.5 cursor-pointer"
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
                                                                try {
                                                                    const newDag =
                                                                        await api.dataModelingDags.create(dagData)
                                                                    await dataModelingLogic.asyncActions.loadDags()
                                                                    onSelect(newDag.id)
                                                                    lemonToast.success('DAG created')
                                                                } catch (error) {
                                                                    lemonToast.error(
                                                                        error instanceof ApiError
                                                                            ? (error.detail ?? 'Failed to create DAG')
                                                                            : 'Failed to create DAG'
                                                                    )
                                                                    // Re-throw so the dialog stays open for the user to retry.
                                                                    throw error
                                                                }
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
                                <LemonField name="materializeAfterSave" className="mt-2">
                                    {({ value, onChange }) => (
                                        <div className="flex items-center gap-2">
                                            <LemonCheckbox
                                                checked={value}
                                                onChange={onChange}
                                                data-attr="sql-editor-input-save-view-materialize"
                                                label="Materialize this view"
                                            />
                                            <Tooltip title="Pre-compute the results into a table for faster queries. Syncs daily by default — you can adjust the frequency later in the view's materialization settings.">
                                                <span className="text-muted cursor-pointer">&#9432;</span>
                                            </Tooltip>
                                        </div>
                                    )}
                                </LemonField>
                                <SaveTargetCycler
                                    candidates={candidates}
                                    onChange={(q) => {
                                        selectedRef.current = q
                                    }}
                                />
                            </>
                        ),
                    errors: {
                        viewName: validateSavedQueryName,
                        dagId: (dagId) => (multiDagEnabled && !dagId ? 'Please select a DAG' : undefined),
                    },
                    onSubmit: async ({
                        viewName,
                        dagId,
                        folderId,
                        isTest,
                        materializeAfterSave: shouldMaterialize,
                    }) => {
                        await asyncActions.saveAsViewSubmit(
                            viewName,
                            shouldMaterialize ?? false,
                            fromDraft,
                            dagId,
                            folderId,
                            isTest ?? false,
                            selectedRef.current
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
                folderId,
                isTest = false,
                queryOverride,
            }) => {
                const query: HogQLQuery = values.sourceQuery.source

                const queryToSave = normalizeRawQuerySource({
                    ...query,
                    query: queryOverride ?? values.queryInput ?? '',
                })

                const logic = dataNodeLogic({
                    key: values.dataLogicKey,
                    query: queryToSave,
                })

                const response = logic.values.response
                const types = response && 'types' in response ? (response.types ?? []) : []
                // "Partial save" means the user is saving something smaller than the full editor
                // text — either because of multi-query splitting or a specific text selection. In
                // that case the current tab shouldn't be rebound to the new view, because its
                // content is NOT the view's content. We tag the view name so the success listener
                // knows to skip its normal bind-to-tab behavior, then open the view in its own tab.
                const isPartialSave = queryToSave.query.trim() !== (values.queryInput ?? '').trim()
                if (isPartialSave) {
                    if (!cache.viewNamesToSkipTabBinding) {
                        cache.viewNamesToSkipTabBinding = new Set<string>()
                    }
                    cache.viewNamesToSkipTabBinding.add(name)
                }
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
                    const savedQuery = dataWarehouseViewsLogic.values.dataWarehouseSavedQueries.find(
                        (q) => q.name === name
                    )

                    if (materializeAfterSave && savedQuery) {
                        await dataWarehouseViewsLogic.asyncActions.materializeDataWarehouseSavedQuery(savedQuery.id)
                    }
                    if (fromDraft) {
                        actions.deleteDraft(fromDraft, savedQuery?.name)
                    }

                    // reload DAGs so newly created default DAG appears
                    dataModelingLogic.findMounted()?.actions.loadDags()

                    if (isPartialSave && savedQuery) {
                        actions.createTab(savedQuery.query?.query ?? queryToSave.query, savedQuery)
                    }
                } catch {
                    lemonToast.error('Failed to save view')
                    // On failure, drop the skip marker so a retry with the same name binds normally.
                    cache.viewNamesToSkipTabBinding?.delete(name)
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

                // Builder insights: display comes from the builder's chart picker, and the save
                // candidates (derived from the Monaco base SQL) must not replace the compiled SQL.
                // When the builder doesn't host the tab it is a plain SQL tab and saves like one.
                const isBuilderInsight = values.insightBuilderHosted && !!currentVisualizationQuery.builder?.enabled

                const defaultDisplay = isBuilderInsight
                    ? (currentVisualizationQuery.display ?? ChartDisplayType.ActionsTable)
                    : getDisplayTypeToSaveInsight(
                          values.outputActiveTab,
                          currentVisualizationQuery.display,
                          effectiveVisualizationType
                      )

                const candidates = resolveSaveCandidates()
                const selectedRef = {
                    current: isBuilderInsight ? undefined : candidates.queries[candidates.initialIndex],
                }

                const insightPreview = (query: string): JSX.Element => (
                    <div className="bg-bg-light max-h-[60vh] overflow-auto">
                        <Suspense fallback={<Spinner />}>
                            <LazyQuery
                                readOnly
                                embedded
                                query={{
                                    ...currentVisualizationQuery,
                                    source: {
                                        ...currentVisualizationQuery.source,
                                        query,
                                    },
                                    display: defaultDisplay,
                                }}
                            />
                        </Suspense>
                    </div>
                )

                LemonDialog.openForm({
                    title: 'Save as new insight',
                    initialValues: {
                        name: '',
                    },
                    content: (
                        <>
                            <LemonField name="name">
                                <LemonInput
                                    data-attr="insight-name"
                                    placeholder="Please enter the new name"
                                    autoFocus
                                />
                            </LemonField>
                            {isBuilderInsight ? (
                                insightPreview(currentVisualizationQuery.source.query)
                            ) : (
                                <SaveTargetCycler
                                    candidates={candidates}
                                    onChange={(q) => {
                                        selectedRef.current = q
                                    }}
                                >
                                    {(query) => insightPreview(query)}
                                </SaveTargetCycler>
                            )}
                        </>
                    ),
                    errors: {
                        name: (name) => (!name ? 'You must enter a name' : undefined),
                    },
                    onSubmit: async ({ name }) => actions.saveAsInsightSubmit(name, selectedRef.current),
                })
            },
            saveAsInsightSubmit: async ({ name, queryOverride }) => {
                const currentVisualizationQuery = getCurrentVisualizationQuery(values.dataLogicKey, values.sourceQuery)
                const effectiveVisualizationType = dataVisualizationLogic.findMounted({
                    key: values.dataLogicKey,
                    query: currentVisualizationQuery,
                    dataNodeCollectionId: values.dataLogicKey,
                    editMode: true,
                })?.values.effectiveVisualizationType

                // A save-candidate override would replace the compiled SQL with the base SQL
                const isBuilderInsight = values.insightBuilderHosted && !!currentVisualizationQuery.builder?.enabled
                const effectiveQueryOverride = isBuilderInsight ? undefined : queryOverride

                const display = isBuilderInsight
                    ? (currentVisualizationQuery.display ?? ChartDisplayType.ActionsTable)
                    : getDisplayTypeToSaveInsight(
                          values.outputActiveTab,
                          currentVisualizationQuery.display,
                          effectiveVisualizationType
                      )

                const sourceQueryToSave: DataVisualizationNode = {
                    ...currentVisualizationQuery,
                    // A new insight saved from the plain SQL editor must not inherit a visual
                    // setup that doesn't describe its query (a stale builder insight opened classic)
                    ...(isBuilderInsight ? {} : { builder: undefined }),
                    source: {
                        ...currentVisualizationQuery.source,
                        query: effectiveQueryOverride ?? currentVisualizationQuery.source.query,
                    },
                    display,
                }

                const dashboardId = values.dashboardId
                const insight = await insightsApi.create({
                    name,
                    query: sourceQueryToSave,
                    saved: true,
                    ...(dashboardId ? { dashboards: [dashboardId] } : {}),
                })
                const logic = insightLogic({
                    dashboardItemId: insight.short_id,
                    doNotLoad: true,
                })
                const umount = logic.mount()
                logic.actions.setInsight(insight, {
                    fromPersistentApi: true,
                    overrideQuery: true,
                })
                const timeoutId = window.setTimeout(() => umount(), 1000 * 10) // keep mounted for 10 seconds while we redirect
                cache.timeouts = cache.timeouts || []
                cache.timeouts.push(timeoutId)

                // A builder save consumes the whole tab session — reset to a blank query before
                // leaving, so returning to the SQL editor doesn't resurrect a stale, unlinked
                // copy of the insight that was just saved. (The reset's URL writes land before
                // the navigation below, and the debounced setQueryInput sync is guarded against
                // stealing the URL back.)
                if (isBuilderInsight) {
                    actions.createTab()
                    actions.setSourceQuery({
                        kind: NodeKind.DataVisualizationNode,
                        source: { kind: NodeKind.HogQLQuery, query: '' },
                        display: ChartDisplayType.Auto,
                    })
                    actions.setActiveTab(OutputTab.Results)
                }

                if (dashboardId) {
                    dashboardsModel.findMounted()?.actions.updateDashboardInsight(insight)
                    dashboardLogic.findMounted({ id: dashboardId })?.actions.loadDashboard({
                        action: DashboardLoadAction.Update,
                    })
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
                const candidates = resolveSaveCandidates()
                const selectedRef = {
                    current: candidates.queries[candidates.initialIndex],
                }
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
                            <SaveTargetCycler
                                candidates={candidates}
                                onChange={(q) => {
                                    selectedRef.current = q
                                }}
                            />
                        </>
                    ),
                    errors: {
                        name: (name) => validateEndpointName(name?.trim() || ''),
                    },
                    onSubmit: async ({ name, description }) =>
                        actions.saveAsEndpointSubmit(name, description, selectedRef.current),
                })
            },
            saveAsEndpointSubmit: async ({ name, description, queryOverride }) => {
                try {
                    const endpoint = await api.endpoint.create({
                        name: slugify(name),
                        description: description || undefined,
                        query: normalizeRawQuerySource({
                            ...(values.sourceQuery.source as HogQLQuery),
                            query: queryOverride ?? values.queryInput ?? '',
                        }),
                    })
                    lemonToast.success('Endpoint created')
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateFirstEndpoint)
                    router.actions.push(urls.endpoint(endpoint.name))
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create endpoint')
                }
            },
            saveAsMetric: async () => {
                const candidates = resolveSaveCandidates()
                const selectedRef = { current: candidates.queries[candidates.initialIndex] }
                LemonDialog.openForm({
                    title: 'Save as metric',
                    initialValues: { name: '', description: '' },
                    content: (
                        <>
                            <LemonField name="name" label="Name">
                                <LemonInput placeholder="monthly_active_users" autoFocus />
                            </LemonField>
                            <LemonField name="description" label="Description" className="mt-2">
                                <LemonInput placeholder="What this metric measures and how to read it" />
                            </LemonField>
                            <SaveTargetCycler
                                candidates={candidates}
                                onChange={(q) => {
                                    selectedRef.current = q
                                }}
                            />
                        </>
                    ),
                    errors: {
                        name: (name) => validateMetricName(name?.trim() || ''),
                        description: (description) => (!description?.trim() ? 'Add a description' : undefined),
                    },
                    onSubmit: async ({ name, description }) =>
                        actions.saveAsMetricSubmit(name.trim(), description.trim(), selectedRef.current),
                })
            },
            saveAsMetricSubmit: async ({ name, description, queryOverride }) => {
                try {
                    const metric = await dataCatalogMetricsCreate(String(ApiConfig.getCurrentTeamId()), {
                        name,
                        description,
                        definition: normalizeRawQuerySource({
                            ...(values.sourceQuery.source as HogQLQuery),
                            query: queryOverride ?? values.queryInput ?? '',
                        }) as unknown as Record<string, unknown>,
                    })
                    lemonToast.success('Metric created')
                    router.actions.push(urls.dataCatalogMetric(metric.name))
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create metric')
                }
            },
            updateEditingMetric: async () => {
                if (!values.editingMetricName || values.metricUpdating) {
                    return
                }
                actions.setMetricUpdating(true)
                try {
                    await dataCatalogMetricsPartialUpdate(
                        String(ApiConfig.getCurrentTeamId()),
                        values.editingMetricName,
                        {
                            definition: normalizeRawQuerySource({
                                ...(values.sourceQuery.source as HogQLQuery),
                                query: values.queryInput ?? '',
                            }) as unknown as Record<string, unknown>,
                        }
                    )
                    lemonToast.success('Metric updated')
                    router.actions.push(urls.dataCatalogMetric(values.editingMetricName))
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to update metric')
                } finally {
                    actions.setMetricUpdating(false)
                }
            },
            setEditingMetricName: ({ metricName }) => {
                if (values.activeTab) {
                    actions.updateTab({ ...values.activeTab, metricName: metricName ?? undefined })
                }
            },
            setEditingInsightName: ({ name }) => {
                if (values.activeTab) {
                    actions.updateTab({ ...values.activeTab, name })
                }
            },
            setEditingInsightDescription: ({ description }) => {
                if (values.activeTab) {
                    actions.updateTab({ ...values.activeTab, description })
                }
            },
            updateInsight: async () => {
                if (!values.editingInsight) {
                    return
                }

                actions.setInsightLoading(true)

                const insightName = values.activeTab?.name
                const insightDescription = values.activeTab?.description
                const currentVisualizationQuery = getCurrentVisualizationQuery(values.dataLogicKey, values.sourceQuery)
                const isBuilderInsight = values.insightBuilderHosted && !!currentVisualizationQuery.builder?.enabled

                const insightRequest: Partial<QueryBasedInsightModel> = {
                    description: insightDescription ?? values.editingInsight.description ?? '',
                    // Updating from the plain SQL editor (a stale builder insight opened classic)
                    // must not persist a visual setup that no longer describes the edited query —
                    // mirrors the same strip in saveAsInsightSubmit
                    query: isBuilderInsight
                        ? currentVisualizationQuery
                        : { ...currentVisualizationQuery, builder: undefined },
                }
                // Only send `name` on an actual rename — the tab name falls back to derived_name
                // (or "Untitled"), and writing that back would materialize it as the insight's name
                if (insightName && insightName !== insightTabName(values.editingInsight)) {
                    insightRequest.name = insightName
                }

                // When saving from a dashboard flow, attach the tile server-side without
                // dropping the insight's existing dashboard links.
                const dashboardId = values.dashboardId
                if (dashboardId) {
                    const existingDashboardIds = [
                        ...(values.editingInsight.dashboard_tiles?.map((tile) => tile.dashboard_id) ?? []),
                        ...(values.editingInsight.dashboards ?? []),
                    ]
                    insightRequest.dashboards = Array.from(new Set([...existingDashboardIds, dashboardId]))
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
                insightsModel.findMounted()?.actions.renameInsightSuccess(savedInsight)
                const loadedLogic = insightLogic.findMounted({
                    dashboardItemId: values.editingInsight.short_id,
                    dashboardId: undefined,
                })
                if (loadedLogic) {
                    loadedLogic.actions.setInsight(savedInsight, {
                        overrideQuery: true,
                        fromPersistentApi: true,
                    })
                }

                if (dashboardId) {
                    dashboardsModel.findMounted()?.actions.updateDashboardInsight(savedInsight)
                    dashboardLogic.findMounted({ id: dashboardId })?.actions.loadDashboard({
                        action: DashboardLoadAction.Update,
                    })
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
                actions.setViewQueryLoading(false)

                if (!values.activeTab) {
                    actions.createTab(values.queryInput ?? '')
                    return
                }

                const nextActiveTab = {
                    ...values.activeTab,
                    name: NEW_QUERY,
                    description: '',
                    view: undefined,
                    insight: undefined,
                    builderHosted: undefined,
                    draft: undefined,
                }

                actions.updateTab(nextActiveTab)
                // A stale insight opened classic keeps its builder config on the node for the
                // whole session (nothing strips mid-session). Once the tab stops editing that
                // insight it becomes a fresh, possibly builder-hosted tab — a leftover enabled
                // config would make the next Run adopt the stale wells and rewrite the SQL.
                if (values.sourceQuery.builder) {
                    actions.setSourceQuery({ ...values.sourceQuery, builder: undefined })
                }

                if (!values.isEmbeddedMode) {
                    const nextHash = encodeURIComponent(
                        JSON.stringify(getTabHash({ ...values, activeTab: nextActiveTab }))
                    )
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
                        const viewWithQuery = {
                            ...updatedView,
                            query: values.activeTab.view.query,
                        }
                        actions.updateTab({
                            ...values.activeTab,
                            view: viewWithQuery,
                        })
                    }
                }
            },
            deleteDataWarehouseSavedQuerySuccess: ({ payload: viewId }) => {
                if (values.activeTab?.view?.id === viewId && !values.activeTab?.draft) {
                    // createTab() alone reuses the existing model and doesn't clear queryInput
                    applyUndoableModelEdit(props.monaco, values.activeTab?.uri, '')
                    actions.setQueryInput('')
                    actions.createTab()
                }
            },
            createDataWarehouseSavedQuerySuccess: ({ dataWarehouseSavedQueries, payload: view }) => {
                if (view?.name && cache.viewNamesToSkipTabBinding?.has(view.name)) {
                    cache.viewNamesToSkipTabBinding.delete(view.name)
                    return
                }
                const newView = view && dataWarehouseSavedQueries.find((v) => v.name === view.name)
                if (newView) {
                    const oldTab = values.activeTab
                    // Only update the tab if it doesn't have a view (new query being saved)
                    // or if it's the same view being recreated (edge case)
                    if (oldTab && (!oldTab.view || oldTab.view.id === newView.id)) {
                        const nextTab = {
                            ...oldTab,
                            name: newView.name,
                            view: view?.query ? { ...newView, query: view.query } : newView,
                        }

                        actions.updateTab(nextTab)

                        if (!values.isEmbeddedMode) {
                            router.actions.replace(
                                urls.sqlEditor(),
                                undefined,
                                getTabHash({ ...values, activeTab: nextTab })
                            )
                        }
                    }
                }
            },
            reviewViewUpdate: ({ view, draftId }) => {
                // Reuse the editor's inline accept/reject diff (QueryPane) instead of a separate
                // modal: show the saved query alongside the user's edits, and only run the update
                // once they accept. Mirrors the conflict-review diff in updateView below.
                const savedQuery = values.activeTab?.view?.query?.query ?? ''
                const editedQuery = values.queryInput ?? ''
                if (savedQuery === editedQuery) {
                    actions.updateView(view, draftId)
                    return
                }
                actions._setSuggestionPayload({
                    suggestedValue: editedQuery,
                    originalValue: savedQuery,
                    acceptText: view.shouldRematerialize ? 'Update and re-materialize view' : 'Update view',
                    rejectText: 'Cancel',
                    diffShowRunButton: false,
                    onAccept: () => {
                        actions.updateView(view, draftId)
                    },
                    onReject: () => {},
                })
            },
            updateView: async ({ view, draftId }) => {
                const latestView = await api.dataWarehouseSavedQueries.get(view.id)
                // A real conflict means someone else changed the query text since this edit began.
                // Detect it by comparing the server's current query against the baseline this edit
                // started from (the tab's saved query) — not against the user's edited query, which
                // always differs. Keying off history ids alone gives false positives when the
                // editor's cached head has drifted from the server's (e.g. the head advanced for a
                // non-query reason, or the view was opened without one), wrongly telling a sole
                // editor the view was changed by someone else.
                const baselineQuery = values.activeTab?.view?.query?.query
                const foreignEdit =
                    latestView?.latest_history_id != null &&
                    baselineQuery != null &&
                    latestView.query?.query !== baselineQuery
                if (foreignEdit) {
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
                    // No foreign edit — send the server's current head so the backend's own
                    // edited_history_id check accepts the save even if the editor's cached head drifted.
                    await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery({
                        ...view,
                        edited_history_id: latestView?.latest_history_id ?? view.edited_history_id,
                    })
                    actions.updateViewSuccess(view, draftId)
                }
            },
            updateViewSuccess: async ({ view, draftId }) => {
                if (draftId) {
                    actions.deleteDraft(draftId, view?.name)
                }
                if (values.activeTab?.view && values.activeTab.view.id === view.id && view.query) {
                    // Refresh the baseline query immediately so `changesToSave` reflects the just-saved
                    // state (and the Update button disables) before we go back to the network.
                    actions.updateTab({
                        ...values.activeTab,
                        view: { ...values.activeTab.view, query: view.query },
                    })
                    // Re-read the server's activity-log head and adopt it as the new base. The concurrency
                    // check — both the frontend guard and the backend's edited_history_id check — keys off
                    // this head; without re-basing, reverting the query and saving again is misread as a
                    // foreign edit and wrongly raises "View has been edited by another user".
                    const refreshedView = await api.dataWarehouseSavedQueries.get(view.id)
                    if (refreshedView?.latest_history_id && values.activeTab?.view?.id === view.id) {
                        actions.updateTab({
                            ...values.activeTab,
                            view: { ...values.activeTab.view, latest_history_id: refreshedView.latest_history_id },
                        })
                        // Point the edit marker at the new head directly (not just clear it) so a fast
                        // revert-and-save can't re-base on the stale pre-save head before this refetch lands.
                        actions.setInProgressViewEdit(view.id, refreshedView.latest_history_id)
                    } else {
                        // No head to adopt — clear the stale marker and let the next edit re-base.
                        actions.deleteInProgressViewEdit(view.id)
                    }
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
        }
    }),
    subscriptions(({ actions, values, cache, props }) => ({
        queryInput: (queryInput: string | null) => {
            // Subquery validation results are keyed by subquery text — but the same text
            // may now refer to a subquery with different surrounding context, so drop
            // everything whenever the editor content changes.
            cache.subqueryValidationCache?.clear()

            // Debounced — updating decorations parses the AST and can hit the metadata endpoint,
            // which is too expensive to run on every keystroke.
            cache.scheduleActiveQueryDecoration?.()

            // Skip re-parsing if the text hasn't changed since the last parse.
            if (cache.lastParsedQueryInput === queryInput && cache.lastParsedQueryResult !== undefined) {
                actions.setSelectedQueryTablesAndColumns(cache.lastParsedQueryResult)
                return
            }

            // Debounce parsing — it walks the HogQL AST and is too heavy to run on every keystroke.
            if (cache.queryInputParseTimeout) {
                window.clearTimeout(cache.queryInputParseTimeout)
            }
            cache.pendingParsedQueryInput = queryInput
            cache.queryInputParseTimeout = window.setTimeout(async () => {
                cache.queryInputParseTimeout = null
                const scheduledInput = cache.pendingParsedQueryInput
                const result = await parseQueryTablesAndColumns(scheduledInput)
                // Drop the result if a newer value was scheduled while we were parsing.
                if (cache.pendingParsedQueryInput !== scheduledInput) {
                    return
                }
                cache.lastParsedQueryInput = scheduledInput
                cache.lastParsedQueryResult = result
                actions.setSelectedQueryTablesAndColumns(result)
            }, 200)
        },
        hasFiltersPlaceholder: (hasFiltersPlaceholder: boolean) => {
            if (hasFiltersPlaceholder) {
                if (typeof values.sourceQuery.source.filters !== 'object') {
                    actions.setSourceQuery({
                        ...values.sourceQuery,
                        source: {
                            ...values.sourceQuery.source,
                            filters: {},
                        },
                    })
                }
            }
        },
        sourceQuery: (sourceQuery: DataVisualizationNode, previousSourceQuery: DataVisualizationNode | undefined) => {
            if (values.isEmbeddedMode || !values.activeTab) {
                return
            }

            const filters = normalizeFiltersForUrl(sourceQuery.source.filters)
            const previousFilters = normalizeFiltersForUrl(previousSourceQuery?.source.filters)
            if (!equal(filters ?? {}, previousFilters ?? {})) {
                actions.syncUrlWithQuery()
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
            claimConnectionScope(props.tabId, selectedConnectionId)
            actions.setConnection(selectedConnectionId ?? null)
            actions.loadDatabase()
            if (selectedConnectionId) {
                // Capability data must load wherever a connection is in play — including
                // surfaces that never render the connection selector.
                actions.maybeLoadConnectionOptions()
            }
            actions.enforceConnectionRawQueryMode()
        },
    })),
    selectors({
        suggestedSource: [
            (s) => [s.suggestionPayload],
            (suggestionPayload: SuggestionPayload | null) => {
                return suggestionPayload?.source ?? null
            },
        ],
        diffShowRunButton: [
            (s) => [s.suggestionPayload],
            (suggestionPayload: SuggestionPayload | null) => {
                return suggestionPayload?.diffShowRunButton
            },
        ],
        acceptText: [
            (s) => [s.suggestionPayload],
            (suggestionPayload: SuggestionPayload | null) => {
                return suggestionPayload?.acceptText ?? 'Accept'
            },
        ],
        rejectText: [
            (s) => [s.suggestionPayload],
            (suggestionPayload: SuggestionPayload | null) => {
                return suggestionPayload?.rejectText ?? 'Reject'
            },
        ],

        suggestedQueryInput: [
            (s) => [s.suggestionPayload, s.queryInput],
            (suggestionPayload: SuggestionPayload | null, queryInput: string | null) => {
                if (suggestionPayload?.suggestedValue && suggestionPayload?.suggestedValue !== queryInput) {
                    return suggestionPayload?.suggestedValue ?? ''
                }

                return queryInput ?? ''
            },
        ],
        originalQueryInput: [
            (s) => [s.suggestionPayload, s.queryInput],
            (suggestionPayload: SuggestionPayload | null, queryInput: string | null) => {
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
            (activeTab: QueryTab | null) => {
                return activeTab?.view
            },
        ],
        editingMetricName: [
            (s) => [s.activeTab],
            (activeTab: QueryTab | null) => {
                return activeTab?.metricName ?? null
            },
        ],
        changesToSave: [
            (s) => [s.editingView, s.queryInput],
            (editingView: DataWarehouseSavedQuery | undefined, queryInput: string | null) => {
                return editingView?.query?.query !== queryInput
            },
        ],
        exportContext: [
            (s) => [s.sourceQuery],
            (sourceQuery: DataVisualizationNode) => {
                // TODO: use active tab at some point
                const filename = 'export'

                return {
                    ...queryExportContext(sourceQuery.source, undefined, undefined),
                    filename,
                } as ExportContext
            },
        ],
        // A second data node keyed off the main one holds the *base* query's raw rows on builder
        // tabs, so the Source tab can show source data while the chart keeps its compiled results
        baseDataLogicKey: [(s) => [s.dataLogicKey], (dataLogicKey: string) => `${dataLogicKey}-base`],
        basePreviewSource: [
            (s) => [s.sourceQuery],
            (sourceQuery: DataVisualizationNode): HogQLQuery | null => {
                const baseQuery = sourceQuery.builder?.enabled ? sourceQuery.builder.baseQuery : ''
                if (!baseQuery.trim()) {
                    return null
                }
                return { ...sourceQuery.source, query: baseQuery }
            },
        ],
        baseExportContext: [
            (s) => [s.basePreviewSource],
            (basePreviewSource: HogQLQuery | null): ExportContext | undefined =>
                basePreviewSource
                    ? ({
                          ...queryExportContext(basePreviewSource, undefined, undefined),
                          filename: 'export',
                      } as ExportContext)
                    : undefined,
        ],
        selectedConnectionId: [
            (s) => [s.sourceQuery],
            (sourceQuery: DataVisualizationNode) => {
                return sourceQuery.source && 'connectionId' in sourceQuery.source
                    ? sourceQuery.source.connectionId
                    : undefined
            },
        ],
        selectedDirectSource: [
            (s) => [s.dataWarehouseSources, s.selectedConnectionId],
            (
                dataWarehouseSources: null | import('lib/api').PaginatedResponse<ExternalDataSource>,
                selectedConnectionId: string | undefined
            ): ExternalDataSource | undefined => {
                return dataWarehouseSources?.results.find((source) => source.id === selectedConnectionId)
            },
        ],
        sendRawQueryEnabled: [
            (s) => [s.sourceQuery, s.selectedConnectionId],
            (sourceQuery: DataVisualizationNode, selectedConnectionId: string | undefined) =>
                !!selectedConnectionId && (sourceQuery.source.sendRawQuery ?? false),
        ],
        selectedConnectionSupportsHogQL: [
            (s) => [s.connectionOptions, s.selectedConnectionId],
            (
                connectionOptions: ExternalDataSourceConnectionOptionApi[] | null,
                selectedConnectionId: string | undefined
            ): boolean => {
                if (!selectedConnectionId) {
                    return true
                }
                const option = connectionOptions?.find((option) => option.id === selectedConnectionId)
                // Unknown connections (options still loading) default to HogQL.
                return option ? option.supports_hogql !== false : true
            },
        ],
        isEditingMaterializedView: [
            (s) => [s.editingView],
            (editingView: DataWarehouseSavedQuery | undefined) => {
                return !!editingView?.is_materialized
            },
        ],
        splitQueryRanges: [
            (s) => [s.queryInput],
            (queryInput: string | null): QueryRange[] => splitQueries(queryInput ?? ''),
        ],
        isMultiQuery: [(s) => [s.splitQueryRanges], (ranges: QueryRange[]): boolean => ranges.length > 1],
        isSourceQueryLastRun: [
            (s) => [s.queryInput, s.lastRunQuery, s.sourceQuery, s.splitQueryRanges, s.insightBuilderHosted],
            (
                queryInput: string | null,
                lastRunQuery: DataVisualizationNode | null,
                sourceQuery: DataVisualizationNode,
                splitRanges: QueryRange[],
                insightBuilderHosted: boolean
            ) => {
                // Builder-hosted tabs: queryInput holds the base SQL while source.query holds the
                // compiled SQL, so compare the compiled texts instead of the Monaco buffer. When
                // the builder doesn't host the tab the buffer is the source of truth like any
                // plain SQL tab.
                if (insightBuilderHosted && sourceQuery.builder?.enabled) {
                    return (lastRunQuery?.source.query ?? '').trim() === (sourceQuery.source.query ?? '').trim()
                }
                const lastRunQueryText = (lastRunQuery?.source.query ?? sourceQuery.source.query ?? '').trim()
                if ((queryInput ?? '').trim() === lastRunQueryText) {
                    return true
                }
                // Multi-query editor: if the last-run text matches any statement in the script,
                // consider it "up to date" — the save flow resolves the target query at submit time.
                return splitRanges.some((q) => q.query.trim() === lastRunQueryText)
            },
        ],
        hasFiltersPlaceholder: [
            (s) => [s.queryInput],
            (queryInput: string | null) => {
                return queryUsesFiltersPlaceholder(queryInput)
            },
        ],
        hasQueryInput: [(s) => [s.queryInput], (queryInput: string | null) => !!queryInput],
        isEmbeddedMode: [
            () => [(_, p: SqlEditorLogicProps) => p.mode],
            (mode: SQLEditorMode | undefined) => isEmbeddedSQLEditorMode(mode ?? SQLEditorMode.FullScene),
        ],
        // Whether the insight builder canvas hosts this tab's visualization. Insight tabs use the
        // one-shot decision made when the insight opened (builder config present and describing
        // the SQL — never the flag, and never re-read from the live node, so mid-session SQL edits
        // can't flip the layout). Non-insight tabs are the creation surface, gated by the flag.
        // Fresh-tab hosting deliberately reads the flag live rather than snapshotting it: flags
        // can arrive after createTab on a cold reload, and a late flip on an empty tab is harmless
        // (no builder config exists to strip or re-attach).
        insightBuilderHosted: [
            (s) => [s.featureFlags, s.isEmbeddedMode, s.activeTab],
            (featureFlags: FeatureFlagsSet, isEmbeddedMode: boolean, activeTab: QueryTab | null): boolean => {
                if (isEmbeddedMode) {
                    return false
                }
                if (activeTab?.insight) {
                    return !!activeTab.builderHosted
                }
                return !!featureFlags[FEATURE_FLAGS.BI_SQL_INSIGHT_EDITOR]
            },
        ],
        dataLogicKey: [(_, p) => [p.tabId], (tabId: string) => `data-warehouse-editor-data-node-${tabId}`],
        isDraft: [(s) => [s.activeTab], (activeTab: QueryTab | null) => (activeTab ? !!activeTab.draft?.id : false)],
        currentDraft: [(s) => [s.activeTab], (activeTab: QueryTab | null) => (activeTab ? activeTab.draft : null)],
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
    trackedActionToUrl(({ values }) => ({
        syncUrlWithQuery: () => {
            if (values.isEmbeddedMode) {
                return
            }
            // Reaches here debounced (setQueryInput waits 500ms), so a save/redirect can have
            // navigated away in the meantime — never steal the URL back to the editor
            if (removeProjectIdIfPresent(router.values.location.pathname) !== urls.sqlEditor()) {
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
    urlToAction(({ actions, values, props }) => ({
        [urls.sqlEditor()]: async (_, searchParams, hashParams) => {
            if (isEmbeddedSQLEditorMode(props.mode ?? SQLEditorMode.FullScene)) {
                return
            }

            if (
                searchParams.source === 'endpoint' ||
                searchParams.source === 'insight' ||
                searchParams.source === 'view' ||
                searchParams.source === 'metric'
            ) {
                actions.setEditorSource(searchParams.source)
            }
            if (searchParams.dashboard) {
                const parsed = parseInt(searchParams.dashboard, 10)
                if (!isNaN(parsed)) {
                    actions.setDashboardId(parsed)
                }
            }

            const outputTabFromUrl = parseOutputTab(searchParams.output_tab ?? hashParams.output_tab)
            const draftIdFromUrl = searchParams.open_draft || hashParams.draft
            const viewIdFromUrl = searchParams.open_view || hashParams.view
            const insightShortIdFromUrl = searchParams.open_insight || hashParams.insight
            const hasFiltersHashParam = hasOwnProperty(hashParams, 'filters')
            const shouldApplyFiltersFromUrl =
                hasFiltersHashParam ||
                (!!(searchParams.open_query || hashParams.q) &&
                    !draftIdFromUrl &&
                    !viewIdFromUrl &&
                    !insightShortIdFromUrl)
            const filtersFromUrl = hasFiltersHashParam ? parseFiltersFromUrl(hashParams.filters) : undefined
            const biEditorStateFromUrl = parseBIEditorState(hashParams.mode, hashParams.bi)
            const applyFiltersFromUrl = (sourceQuery: DataVisualizationNode): DataVisualizationNode => {
                if (!shouldApplyFiltersFromUrl) {
                    return sourceQuery
                }

                return {
                    ...sourceQuery,
                    source: {
                        ...sourceQuery.source,
                        filters: filtersFromUrl ?? {},
                    },
                }
            }
            const expectedDatabaseConnectionId = values.selectedConnectionId ?? null
            const shouldSyncDatabaseConnection =
                values.databaseConnectionId !== expectedDatabaseConnectionId || !values.database

            if (
                !searchParams.open_query &&
                !searchParams.open_view &&
                !searchParams.open_insight &&
                !searchParams.open_draft &&
                !searchParams.output_tab &&
                !hashParams.q &&
                !hashParams.c &&
                !hashParams.raw &&
                !hasFiltersHashParam &&
                !hashParams.view &&
                !hashParams.insight &&
                !hashParams.draft &&
                !hashParams.output_tab &&
                !hashParams.mode &&
                !hashParams.bi &&
                values.queryInput !== null
            ) {
                if (shouldSyncDatabaseConnection && !values.databaseLoading) {
                    actions.setConnection(expectedDatabaseConnectionId)
                    actions.loadDatabase()
                }
                return
            }

            const connectionIdFromHash =
                typeof hashParams.c === 'string' && hashParams.c !== '' ? hashParams.c : undefined
            const sendRawQueryFromHash = connectionIdFromHash !== undefined && String(hashParams.raw) === '1'
            const currentConnectionId = values.sourceQuery.source.connectionId || undefined
            const currentSendRawQuery = values.sourceQuery.source.sendRawQuery ?? false
            const filtersForSourceQuery = applyFiltersFromUrl(values.sourceQuery).source.filters
            const shouldSyncFilters =
                shouldApplyFiltersFromUrl &&
                !equal(
                    normalizeFiltersForUrl(filtersForSourceQuery) ?? {},
                    normalizeFiltersForUrl(values.sourceQuery.source.filters) ?? {}
                )

            if (
                connectionIdFromHash !== currentConnectionId ||
                sendRawQueryFromHash !== currentSendRawQuery ||
                shouldSyncFilters
            ) {
                actions.setSourceQuery({
                    ...values.sourceQuery,
                    source: {
                        ...values.sourceQuery.source,
                        connectionId: connectionIdFromHash,
                        sendRawQuery: sendRawQueryFromHash || undefined,
                        filters: filtersForSourceQuery,
                    },
                })
            }

            const createQueryTab = async (): Promise<void> => {
                if (outputTabFromUrl && values.outputActiveTab !== outputTabFromUrl) {
                    actions.setActiveTab(outputTabFromUrl)
                }

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

                        actions.createTab(
                            draft.query.query,
                            associatedView,
                            undefined,
                            draft,
                            undefined,
                            biEditorStateFromUrl ?? undefined
                        )
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
                    actions.setViewQueryLoading(true)

                    if (values.dataWarehouseSavedQueries.length === 0) {
                        await dataWarehouseViewsLogic.asyncActions.loadDataWarehouseSavedQueries()
                    }

                    let view = values.dataWarehouseSavedQueries.find((n) => n.id === viewId)
                    if (!view) {
                        lemonToast.error('View not found')
                        actions.setViewLoading(false)
                        actions.setViewQueryLoading(false)
                        return
                    }

                    // Fetch the full view with query if not already loaded
                    if (!view.query) {
                        try {
                            view = await api.dataWarehouseSavedQueries.get(viewId)
                        } catch {
                            lemonToast.error('Failed to load view details')
                            actions.setViewLoading(false)
                            actions.setViewQueryLoading(false)
                            return
                        }
                    }

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : (view.query?.query ?? '')

                    if (outputTabFromUrl) {
                        actions.createTab(
                            queryToOpen,
                            view,
                            undefined,
                            undefined,
                            undefined,
                            biEditorStateFromUrl ?? undefined
                        )
                    } else {
                        actions.editView(queryToOpen, view, biEditorStateFromUrl ?? undefined)
                    }
                    actions.setViewLoading(false)
                    actions.setViewQueryLoading(false)
                    router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                } else if (
                    insightShortIdFromUrl &&
                    (searchParams.open_insight ||
                        !activeTabMatchesUrlTarget(values.activeTab, {
                            insightShortId: insightShortIdFromUrl,
                        }))
                ) {
                    // The tab is NOT reset before the fetch: hosting derives from the tab, so
                    // clearing the insight here would flip the layout to the flag default for the
                    // whole network wait — and strand the tab half-reset if the fetch fails. On
                    // success createTab rebuilds the tab from the fetched insight anyway.
                    actions._setSuggestionPayload(null)

                    const shortId = insightShortIdFromUrl
                    if (shortId === 'new') {
                        // Add new blank tab
                        actions.createTab(
                            '',
                            undefined,
                            undefined,
                            undefined,
                            undefined,
                            biEditorStateFromUrl ?? undefined
                        )
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

                    // Captured before editInsight/createTab, which reset lastRunQuery to the
                    // incoming insight's query — this is the text the current response answers
                    const previousRunText = values.lastRunQuery?.source.query?.trim()

                    // Builder insights hold compiled SQL in source.query — the Monaco buffer gets
                    // the base query, and runs go through the compiled text explicitly. Decided
                    // from the saved node's content alone (never the flag, which only gates
                    // creating new builder insights); a stale config opens classic — SQL wins.
                    const isBuilderInsight = nodeOpensInBuilder(insightVisualizationQuery)
                    const queryToOpen = searchParams.open_query
                        ? searchParams.open_query
                        : isBuilderInsight && insightVisualizationQuery?.builder
                          ? insightVisualizationQuery.builder.baseQuery
                          : query
                    const builderRunOverride = isBuilderInsight ? query : undefined

                    if (insightVisualizationQuery) {
                        actions.setSourceQuery(applyFiltersFromUrl(insightVisualizationQuery))
                    }
                    actions.editInsight(queryToOpen, insight, biEditorStateFromUrl ?? undefined)
                    // Flip only after the insight is fully in place: the canvas mounting mid-load
                    // proved racy in practice, and the brief Source flash is the safer trade
                    if (!outputTabFromUrl) {
                        actions.setActiveTab(OutputTab.Visualization)
                    }

                    // Only skip the run when the cached (or in-flight) response actually answers
                    // this insight's query — switching between insights in the same tab otherwise
                    // keeps the previous insight's rows on screen under the new chart config
                    if (insightVisualizationQuery && !searchParams.open_query) {
                        const mountedDataLogic = dataNodeLogic.findMounted({
                            key: values.dataLogicKey,
                        })
                        const response = mountedDataLogic?.values.response
                        const responseLoading = mountedDataLogic?.values.responseLoading ?? false
                        const answersThisInsight = previousRunText === query.trim() && (responseLoading || !!response)

                        if (!answersThisInsight) {
                            actions.runQuery(builderRunOverride)
                        }
                    } else {
                        actions.runQuery(builderRunOverride)
                    }

                    router.actions.replace(urls.sqlEditor(), undefined, getTabHash(values))
                } else if (searchParams.edit_metric) {
                    // edit_metric binds the "Update metric" button to overwrite a named metric.
                    // Both edit_metric and open_query are URL-controlled, so we never bind the
                    // update target to URL-supplied SQL — a crafted link could otherwise overwrite
                    // a teammate's metric with arbitrary HogQL. Load the metric server-side and open
                    // its stored query, so the update target and its definition come from the same
                    // authenticated response.
                    try {
                        // Validate before it reaches the request path: the value is interpolated
                        // into the URL unencoded, so a name containing "../" could otherwise
                        // traverse to a metric in another project. The name regex forbids slashes.
                        if (validateMetricName(searchParams.edit_metric)) {
                            throw new Error('Invalid metric name')
                        }
                        const metric = await dataCatalogMetricsRetrieve(
                            String(ApiConfig.getCurrentTeamId()),
                            searchParams.edit_metric
                        )
                        const definition = metric.definition as Record<string, unknown> | null | undefined
                        const metricQuery = typeof definition?.query === 'string' ? definition.query : ''
                        actions.createTab(
                            metricQuery,
                            undefined,
                            undefined,
                            undefined,
                            metric.name,
                            biEditorStateFromUrl ?? undefined
                        )
                    } catch {
                        // Invalid name, metric not found, or no access — open an unbound empty tab
                        // rather than binding an update target we couldn't verify.
                        actions.createTab(
                            '',
                            undefined,
                            undefined,
                            undefined,
                            undefined,
                            biEditorStateFromUrl ?? undefined
                        )
                    }
                } else if (searchParams.open_query) {
                    // kea-router decodes JSON-shaped URL values to objects — a node here carries
                    // visualization settings (display, chartSettings) alongside the SQL
                    const openQueryNode =
                        typeof searchParams.open_query === 'object'
                            ? toDataVisualizationNode(searchParams.open_query)
                            : undefined
                    if (openQueryNode) {
                        actions.createTab(
                            openQueryNode.source.query || '',
                            undefined,
                            undefined,
                            undefined,
                            undefined,
                            biEditorStateFromUrl ?? undefined
                        )
                        actions.setSourceQuery(hasFiltersHashParam ? applyFiltersFromUrl(openQueryNode) : openQueryNode)
                        if (!outputTabFromUrl) {
                            actions.setActiveTab(OutputTab.Visualization)
                        }
                        // Prefill only, don't auto-run: open_query is fully URL-controlled, so running here
                        // would let a crafted link execute arbitrary HogQL in the user's project on load
                    } else {
                        // kea-router also decodes numeric/JSON-shaped values; a non-node object is a
                        // malformed URL, so fall back to an empty query rather than "[object Object]"
                        actions.createTab(
                            typeof searchParams.open_query === 'object' ? '' : String(searchParams.open_query),
                            undefined,
                            undefined,
                            undefined,
                            undefined,
                            biEditorStateFromUrl ?? undefined
                        )
                    }
                } else if (
                    hashParams.q &&
                    !draftIdFromUrl &&
                    !viewIdFromUrl &&
                    !insightShortIdFromUrl &&
                    (values.queryInput === null ||
                        !activeTabMatchesUrlTarget(values.activeTab, {}) ||
                        values.queryInput !== String(hashParams.q))
                ) {
                    // kea-router decodes numeric/JSON-shaped URL values to non-strings; coerce so queryInput stays a string
                    actions.createTab(
                        String(hashParams.q),
                        undefined,
                        undefined,
                        undefined,
                        undefined,
                        biEditorStateFromUrl ?? undefined
                    )
                } else if (values.queryInput === null) {
                    actions.createTab('', undefined, undefined, undefined, undefined, biEditorStateFromUrl ?? undefined)
                }
            }

            // No waiting on Monaco: createTab records the tab's identity without it and the
            // editor content flows through queryInput/`path`; the model URI is backfilled by
            // `initialize` when Monaco mounts.
            await createQueryTab()

            if (connectionIdFromHash === undefined && shouldSyncDatabaseConnection && !values.databaseLoading) {
                actions.setConnection(expectedDatabaseConnectionId)
                actions.loadDatabase()
            }
        },
    })),
    afterMount(({ actions, props, values, cache }) => {
        cache.lastSelectedConnectionId = values.selectedConnectionId
        claimConnectionScope(props.tabId, values.selectedConnectionId)
        cache.activeQueryDecorationIds = [] as string[]
        cache.decorationGeneration = 0

        // Debounce the active-query decoration. It parses the HogQL AST (WASM, main thread) and
        // can fire a HogQLMetadata request, so running it on every keystroke or arrow key stalls
        // typing on long queries. Cursor moves and content changes both schedule through here.
        cache.scheduleActiveQueryDecoration = (): void => {
            if (cache.activeQueryDecorationDebounceTimeout) {
                window.clearTimeout(cache.activeQueryDecorationDebounceTimeout)
            }
            cache.activeQueryDecorationDebounceTimeout = window.setTimeout(() => {
                cache.activeQueryDecorationDebounceTimeout = null
                cache.updateActiveQueryDecoration?.()
            }, 150)
        }

        cache.updateActiveQueryDecoration = async (): Promise<void> => {
            // Bump the generation counter so any still-running invocation bails out before
            // applying stale decorations. Each run owns its own `generation` token.
            const generation = ++cache.decorationGeneration
            const isStale = (): boolean => generation !== cache.decorationGeneration

            const editorInstance = props.editor
            if (!editorInstance?.getPosition || !editorInstance?.getModel) {
                return
            }
            const model = editorInstance.getModel()
            const position = editorInstance.getPosition()
            if (!model || !position) {
                return
            }

            const fullText = values.queryInput ?? ''
            const queries = splitQueries(fullText)
            const cursorOffset = model.getOffsetAt(position)

            // Helper to validate a subquery standalone. Results are cached by subquery text
            // to avoid re-hitting the metadata endpoint for the same subquery on every cursor
            // move; the cache is invalidated whenever queryInput changes (see subscription).
            const validateSubquery = async (subqueryText: string): Promise<{ errorMessage: string | null }> => {
                if (!cache.subqueryValidationCache) {
                    cache.subqueryValidationCache = new Map<string, { errorMessage: string | null }>()
                }
                const cached = cache.subqueryValidationCache.get(subqueryText)
                if (cached) {
                    return cached
                }
                try {
                    const response = await performQuery<HogQLMetadata>({
                        kind: NodeKind.HogQLMetadata,
                        language: HogLanguage.hogQL,
                        query: subqueryText,
                    })
                    const errors = response?.errors ?? []
                    const result =
                        errors.length > 0
                            ? {
                                  errorMessage: `This subquery may fail standalone:\n${errors.map((e) => e.message).join('\n')}`,
                              }
                            : { errorMessage: null }
                    cache.subqueryValidationCache.set(subqueryText, result)
                    return result
                } catch {
                    return { errorMessage: 'This subquery may fail standalone' }
                }
            }

            // Resolve the innermost subquery at the cursor and build:
            //   - the range to draw the outline overlay around
            //   - per-line gutter/glyph decorations when the subquery can't run standalone
            // The outline itself is rendered via a DOM overlay (see renderQueryOutline) rather
            // than an inline className, so it reads as a frame around the code instead of a
            // text background that can be confused with selection.
            const buildSubquery = async (
                activeQuery: QueryRange,
                offset: number
            ): Promise<{ range: IRange | null; decorations: editor.IModelDeltaDecoration[] }> => {
                const subquery = await findInnermostSelectAtOffset(activeQuery.query, offset, activeQuery.start)
                if (!subquery) {
                    return { range: null, decorations: [] }
                }
                const subStart = model.getPositionAt(subquery.start)
                const subEnd = model.getPositionAt(subquery.end)
                const range: IRange = {
                    startLineNumber: subStart.lineNumber,
                    startColumn: subStart.column,
                    endLineNumber: subEnd.lineNumber,
                    endColumn: subEnd.column,
                }
                const { errorMessage } = await validateSubquery(subquery.query)
                const decorations: editor.IModelDeltaDecoration[] = []
                if (errorMessage) {
                    decorations.push({
                        range,
                        options: {
                            linesDecorationsClassName: 'active-subquery-border-invalid',
                            hoverMessage: { value: errorMessage },
                        },
                    })
                    decorations.push({
                        range: {
                            startLineNumber: subStart.lineNumber,
                            startColumn: 1,
                            endLineNumber: subStart.lineNumber,
                            endColumn: 1,
                        },
                        options: {
                            glyphMarginClassName: 'active-subquery-glyph-invalid',
                            glyphMarginHoverMessage: { value: errorMessage },
                        },
                    })
                }
                return { range, decorations }
            }

            const applyResult = (range: IRange | null, decorations: editor.IModelDeltaDecoration[]): void => {
                cache.updateQueryOutline?.(range)
                cache.activeQueryDecorationIds = editorInstance.deltaDecorations(
                    cache.activeQueryDecorationIds ?? [],
                    decorations
                )
            }

            // Single query — outline the innermost subquery at the cursor (which collapses
            // to the whole SELECT when there is no nested subquery).
            if (queries.length <= 1) {
                const singleQuery = queries.length === 1 ? queries[0] : null
                // Offset must be the statement's start in the full text, not 0 — otherwise leading
                // whitespace/newlines desync the metadata markers (squiggles) by that many characters.
                actions.setActiveQueryText(singleQuery?.query ?? null, singleQuery?.start ?? 0)

                if (!singleQuery) {
                    if (isStale()) {
                        return
                    }
                    applyResult(null, [])
                    return
                }

                const { range, decorations } = await buildSubquery(singleQuery, cursorOffset)
                if (isStale()) {
                    return
                }
                applyResult(range, decorations)
                return
            }

            // Multiple queries — outline only the innermost subquery within the active one.
            const match = findQueryAtCursor(queries, cursorOffset)
            if (!match) {
                actions.setActiveQueryText(null, 0)
                if (isStale()) {
                    return
                }
                applyResult(null, [])
                return
            }

            actions.setActiveQueryText(match.query, match.start)

            const { range, decorations } = await buildSubquery(match, cursorOffset)
            if (isStale()) {
                return
            }

            // With several semicolon-separated statements in the editor, the inner-subquery
            // outline alone doesn't tell you which top-level statement Cmd+Enter will run.
            // A soft blue gutter bar spanning the active statement keeps that visible without
            // re-introducing a range-wide background that reads as text selection.
            const matchStart = model.getPositionAt(match.start)
            const matchEnd = model.getPositionAt(match.end)
            decorations.push({
                range: {
                    startLineNumber: matchStart.lineNumber,
                    startColumn: matchStart.column,
                    endLineNumber: matchEnd.lineNumber,
                    endColumn: matchEnd.column,
                },
                options: { linesDecorationsClassName: 'active-query-gutter' },
            })

            applyResult(range, decorations)
        }

        const expectedDatabaseConnectionId = values.selectedConnectionId ?? null
        const shouldSyncDatabaseConnection =
            values.databaseConnectionId !== expectedDatabaseConnectionId || !values.database
        const hasExplicitEditorUrlState =
            window.location.search.length > 0 ||
            window.location.hash.length > 0 ||
            window.location.pathname !== urls.sqlEditor()

        if (
            (isEmbeddedSQLEditorMode(props.mode ?? SQLEditorMode.FullScene) || !hasExplicitEditorUrlState) &&
            shouldSyncDatabaseConnection
        ) {
            actions.setConnection(values.selectedConnectionId ?? null)
            // `databaseTableListLogic` is a shared singleton. If a prior visit left `databaseLoading`
            // stuck true (a load that never settled), the plain guard would skip the reload and the
            // editor would sit on "Loading..." forever. On remount we still need data, so force a
            // fresh request to bypass any hung in-flight load.
            actions.loadDatabase(values.databaseLoading ? { force: true } : undefined)
        }
    }),
    beforeUnmount(({ actions, values, cache, props }) => {
        // The editor scopes the shared schema catalog to whichever connection it was querying, and
        // that logic stays mounted after the editor closes. Hand it back unscoped so pages like the
        // sources list don't render the connection's tables as if they were the project's own. Only
        // once no mounted editor still wants that connection though, or closing one of two editors
        // sharing a connection would leave the survivor with the wrong schema tree.
        if (releaseConnectionScope(props.tabId, values.databaseConnectionId)) {
            actions.resetConnectionScope()
        }

        cache.cursorDisposable?.dispose()
        cache.cursorDisposable = null
        clearQueryOutlineOverlay(cache, props.editor)
        cache.umountDataNode?.()
        cache.umountDataNode = null
        cache.umountBaseDataNode?.()
        cache.umountBaseDataNode = null

        // Drop any pending decoration work so late callbacks don't touch a disposed editor.
        if (cache.activeQueryDecorationDebounceTimeout) {
            window.clearTimeout(cache.activeQueryDecorationDebounceTimeout)
            cache.activeQueryDecorationDebounceTimeout = null
        }
        if (cache.activeQueryFlashTimeout) {
            window.clearTimeout(cache.activeQueryFlashTimeout)
            cache.activeQueryFlashTimeout = null
        }
        if (cache.queryInputParseTimeout) {
            window.clearTimeout(cache.queryInputParseTimeout)
            cache.queryInputParseTimeout = null
        }
        cache.decorationGeneration = (cache.decorationGeneration ?? 0) + 1

        cache.createdModels?.forEach((m: editor.ITextModel) => {
            clearLogicReference(m)
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
