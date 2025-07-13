import { Monaco } from '@monaco-editor/react'
import { LemonDialog, LemonInput, lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { initModel } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { removeUndefinedAndNull } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import isEqual from 'lodash.isequal'
import { editor, Uri } from 'monaco-editor'
import posthog from 'posthog-js'
import { insightsApi } from 'scenes/insights/utils/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import {
    DatabaseSchemaViewTable,
    DataVisualizationNode,
    HogQLMetadataResponse,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    DataWarehouseSavedQuery,
    ExportContext,
    LineageGraph,
    QueryBasedInsightModel,
    QueryTabState,
} from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { DATAWAREHOUSE_EDITOR_ITEM_ID, sizeOfInBytes } from '../utils'
// Removed db import - no longer using local storage
import { editorSceneLogic } from './editorSceneLogic'
import { fixSQLErrorsLogic } from './fixSQLErrorsLogic'
import type { multitabEditorLogicType } from './multitabEditorLogicType'
import { outputPaneLogic, OutputTab } from './outputPaneLogic'
import {
    aiSuggestionOnAccept,
    aiSuggestionOnAcceptText,
    aiSuggestionOnReject,
    aiSuggestionOnRejectText,
} from './suggestions/aiSuggestion'
import { ViewEmptyState } from './ViewLoadingState'

export interface MultitabEditorLogicProps {
    key: string
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

// Removed local storage key constants - now using database-only state management

export const NEW_QUERY = 'Untitled'

const getNextUntitledNumber = (tabs: QueryTab[]): number => {
    const untitledNumbers = tabs
        .filter((tab) => tab.name?.startsWith(NEW_QUERY))
        .map((tab) => {
            const match = tab.name?.match(/Untitled (\d+)/)
            return match ? parseInt(match[1]) : 0
        })
        .filter((num) => !isNaN(num))

    if (untitledNumbers.length === 0) {
        return 1
    }

    // Find the first gap in the sequence or use the next number
    for (let i = 1; i <= untitledNumbers.length + 1; i++) {
        if (!untitledNumbers.includes(i)) {
            return i
        }
    }
    return untitledNumbers.length + 1
}

// Local storage functions removed - now using database-only state management

export interface QueryTab {
    uri: Uri
    view?: DataWarehouseSavedQuery
    name: string
    sourceQuery?: DataVisualizationNode
    insight?: QueryBasedInsightModel
    response?: Record<string, any>
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
        actions: multitabEditorLogicType['actions'],
        values: multitabEditorLogicType['values'],
        props: multitabEditorLogicType['props']
    ) => void
    onReject: (
        actions: multitabEditorLogicType['actions'],
        values: multitabEditorLogicType['values'],
        props: multitabEditorLogicType['props']
    ) => void
}

export const multitabEditorLogic = kea<multitabEditorLogicType>([
    path(['data-warehouse', 'editor', 'multitabEditorLogic']),
    props({} as MultitabEditorLogicProps),
    key((props) => props.key),
    connect(() => ({
        values: [
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById'],
            userLogic,
            ['user'],
        ],
        actions: [
            dataWarehouseViewsLogic,
            [
                'loadDataWarehouseSavedQueriesSuccess',
                'deleteDataWarehouseSavedQuerySuccess',
                'createDataWarehouseSavedQuerySuccess',
                'runDataWarehouseSavedQuery',
                'resetDataModelingJobs',
                'loadDataModelingJobs',
                'updateDataWarehouseSavedQuerySuccess',
                'updateDataWarehouseSavedQueryFailure',
                'updateDataWarehouseSavedQuery',
            ],
            outputPaneLogic,
            ['setActiveTab'],
            editorSceneLogic,
            ['reportAIQueryPrompted', 'reportAIQueryAccepted', 'reportAIQueryRejected', 'reportAIQueryPromptOpen'],
            fixSQLErrorsLogic,
            ['fixErrors', 'fixErrorsSuccess', 'fixErrorsFailure'],
        ],
    })),
    actions(({ values }) => ({
        setQueryInput: (queryInput: string) => ({ queryInput }),
        updateState: (skipBreakpoint?: boolean) => ({ skipBreakpoint }),
        runQuery: (queryOverride?: string, switchTab?: boolean) => ({
            queryOverride,
            switchTab,
        }),
        setActiveQuery: (query: string) => ({ query }),
        renameTab: (tab: QueryTab, newName: string) => ({ tab, newName }),
        setTabs: (tabs: QueryTab[]) => ({ tabs }),
        addTab: (tab: QueryTab) => ({ tab }),
        createTab: (query?: string, view?: DataWarehouseSavedQuery, insight?: QueryBasedInsightModel) => ({
            query,
            view,
            insight,
        }),
        loadUpstream: (modelId: string) => ({ modelId }),
        deleteTab: (tab: QueryTab) => ({ tab }),
        _deleteTab: (tab: QueryTab) => ({ tab }),
        removeTab: (tab: QueryTab) => ({ tab }),
        selectTab: (tab: QueryTab) => ({ tab }),
        updateTab: (tab: QueryTab) => ({ tab }),
        // setLocalState removed - now using database-only state management
        initialize: true,
        saveAsView: (materializeAfterSave = false) => ({ materializeAfterSave }),
        saveAsViewSubmit: (name: string, materializeAfterSave = false) => ({ name, materializeAfterSave }),
        saveAsInsight: true,
        saveAsInsightSubmit: (name: string) => ({ name }),
        updateInsight: true,
        setCacheLoading: (loading: boolean) => ({ loading }),
        setError: (error: string | null) => ({ error }),
        setDataError: (error: string | null) => ({ error }),
        setSourceQuery: (sourceQuery: DataVisualizationNode) => ({ sourceQuery }),
        setMetadata: (metadata: HogQLMetadataResponse | null) => ({ metadata }),
        setMetadataLoading: (loading: boolean) => ({ loading }),
        editView: (query: string, view: DataWarehouseSavedQuery) => ({ query, view }),
        editInsight: (query: string, insight: QueryBasedInsightModel) => ({ query, insight }),
        updateQueryTabState: (skipBreakpoint?: boolean) => ({ skipBreakpoint }),
        setLastRunQuery: (lastRunQuery: DataVisualizationNode | null) => ({ lastRunQuery }),
        _setSuggestionPayload: (payload: SuggestionPayload | null) => ({ payload }),
        setSuggestedQueryInput: (suggestedQueryInput: string, source?: SuggestionPayload['source']) => ({
            suggestedQueryInput,
            source,
        }),
        onAcceptSuggestedQueryInput: (shouldRunQuery?: boolean) => ({ shouldRunQuery }),
        onRejectSuggestedQueryInput: true,
        setResponse: (response: Record<string, any> | null) => ({ response, currentTab: values.activeModelUri }),
        shareTab: true,
        openHistoryModal: true,
        closeHistoryModal: true,
        setInProgressViewEdit: (viewId: string, historyId: string) => ({ viewId, historyId }),
        deleteInProgressViewEdit: (viewId: string) => ({ viewId }),
        updateView: (
            view: Partial<DatabaseSchemaViewTable> & {
                edited_history_id?: string
                id: string
                lifecycle?: string
                shouldRematerialize?: boolean
                sync_frequency?: string
                types: string[][]
            }
        ) => ({ view }),
        setUpstreamViewMode: (mode: 'table' | 'graph') => ({ mode }),
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps.monaco && !oldProps.editor && props.monaco && props.editor) {
            actions.initialize()
        }
    }),
    loaders(({ values }) => ({
        queryTabState: [
            null as QueryTabState | null,
            {
                loadQueryTabState: async () => {
                    if (!values.user) {
                        return null
                    }
                    let queryTabStateModel = null
                    try {
                        queryTabStateModel = await api.queryTabState.user(values.user?.uuid)
                    } catch (e) {
                        console.error(e)
                    }

                    if (queryTabStateModel === null) {
                        queryTabStateModel = await api.queryTabState.create({
                            state: {
                                editorModelsStateKey: '',
                                activeModelStateKey: '',
                                sourceQuery: values.sourceQuery ? JSON.stringify(values.sourceQuery) : '',
                            },
                        })
                    }

                    return queryTabStateModel
                },
            },
        ],
        upstream: [
            null as LineageGraph | null,
            {
                loadUpstream: async (payload: { modelId: string }) => {
                    const upstream = await api.upstream.get(payload.modelId)
                    return upstream
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        cacheLoading: [
            true,
            {
                setCacheLoading: (_, { loading }) => loading,
            },
        ],
        sourceQuery: [
            {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: '',
                },
                display: ChartDisplayType.ActionsLineGraph,
            } as DataVisualizationNode,
            {
                setSourceQuery: (_, { sourceQuery }) => sourceQuery,
            },
        ],
        lastRunQuery: [
            null as DataVisualizationNode | null,
            {
                setLastRunQuery: (_, { lastRunQuery }) => lastRunQuery,
            },
        ],
        queryInput: [
            '',
            {
                setQueryInput: (_, { queryInput }) => queryInput,
            },
        ],
        activeQuery: [
            null as string | null,
            {
                setActiveQuery: (_, { query }) => query,
            },
        ],
        activeModelUri: [
            null as QueryTab | null,
            {
                selectTab: (_, { tab }) => tab,
            },
        ],
        editingInsight: [
            null as QueryBasedInsightModel | null,
            {
                selectTab: (_, { tab }) => tab.insight ?? null,
            },
        ],
        allTabs: [
            [] as QueryTab[],
            { persist: true },
            {
                addTab: (state, { tab }) => {
                    return [...state, tab]
                },
                removeTab: (state, { tab: tabToRemove }) => {
                    return state.filter((tab) => tab.uri.toString() !== tabToRemove.uri.toString())
                },
                setTabs: (_, { tabs }) => tabs,
                updateTab: (state, { tab }) => {
                    return state.map((stateTab) => {
                        if (stateTab.uri.path === tab.uri.path) {
                            return {
                                ...stateTab,
                                ...tab,
                            }
                        }
                        return stateTab
                    })
                },
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
        editorKey: [props.key],
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
            { persist: true },
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
            'table' as 'table' | 'graph',
            {
                setUpstreamViewMode: (_: 'table' | 'graph', { mode }: { mode: 'table' | 'graph' }) => mode,
            },
        ],
    })),
    listeners(({ values, props, actions, asyncActions }) => ({
        fixErrorsSuccess: ({ response }) => {
            actions.setSuggestedQueryInput(response.query, 'hogql_fixer')

            posthog.capture('ai-error-fixer-success', { trace_id: response.trace_id })
        },
        fixErrorsFailure: () => {
            posthog.capture('ai-error-fixer-failure')
        },
        shareTab: () => {
            const currentTab = values.activeModelUri
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
                        shareUrl.searchParams.set('open_query', values.queryInput)
                    }
                }

                void copyToClipboard(shareUrl.toString(), 'share link')
            } else if (currentTab.view) {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_view', currentTab.view.id)

                if (values.queryInput != currentTab.view.query.query) {
                    shareUrl.searchParams.set('open_query', values.queryInput)
                }

                void copyToClipboard(shareUrl.toString(), 'share link')
            } else {
                const currentUrl = new URL(window.location.href)
                const shareUrl = new URL(currentUrl.origin + currentUrl.pathname)
                shareUrl.searchParams.set('open_query', values.queryInput)

                void copyToClipboard(shareUrl.toString(), 'share link')
            }
        },
        setSuggestedQueryInput: ({ suggestedQueryInput, source }) => {
            if (values.queryInput) {
                actions._setSuggestionPayload({
                    suggestedValue: suggestedQueryInput,
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
            if (props.monaco && values.activeModelUri) {
                const existingModel = props.monaco.editor.getModel(values.activeModelUri.uri)
                if (!existingModel) {
                    const newModel = props.monaco.editor.createModel(
                        values.suggestedQueryInput,
                        'hogQL',
                        values.activeModelUri.uri
                    )

                    const mountedCodeEditorLogic =
                        codeEditorLogic.findMounted() ||
                        codeEditorLogic({
                            key: props.key,
                            query: values.suggestedQueryInput,
                            language: 'hogQL',
                        })

                    initModel(newModel, mountedCodeEditorLogic)
                    props.editor?.setModel(newModel)
                } else {
                    props.editor?.setModel(existingModel)
                }
            }
            posthog.capture('sql-editor-accepted-suggestion', { source: values.suggestedSource })
            actions._setSuggestionPayload(null)
            actions.updateState(true)
        },
        onRejectSuggestedQueryInput: () => {
            values.suggestionPayload?.onReject(actions, values, props)

            // Re-create the model to prevent it from being purged
            if (props.monaco && values.activeModelUri) {
                const existingModel = props.monaco.editor.getModel(values.activeModelUri.uri)
                if (!existingModel) {
                    const newModel = props.monaco.editor.createModel(
                        values.queryInput,
                        'hogQL',
                        values.activeModelUri.uri
                    )

                    const mountedCodeEditorLogic =
                        codeEditorLogic.findMounted() ||
                        codeEditorLogic({
                            key: props.key,
                            query: values.queryInput,
                            language: 'hogQL',
                        })

                    initModel(newModel, mountedCodeEditorLogic)
                    props.editor?.setModel(newModel)
                } else {
                    props.editor?.setModel(existingModel)
                }
            }
            posthog.capture('sql-editor-rejected-suggestion', { source: values.suggestedSource })
            actions._setSuggestionPayload(null)
            actions.updateState(true)
        },
        editView: ({ query, view }) => {
            const maybeExistingTab = values.allTabs.find((tab) => tab.view?.id === view.id)
            if (maybeExistingTab) {
                actions.selectTab(maybeExistingTab)
            } else {
                actions.createTab(query, view)
            }
        },
        editInsight: ({ query, insight }) => {
            const maybeExistingTab = values.allTabs.find((tab) => tab.insight?.short_id === insight.short_id)

            if (maybeExistingTab) {
                const updatedTab = { ...maybeExistingTab, insight }
                actions.updateTab(updatedTab)
                actions.selectTab(updatedTab)
            } else {
                // Create a new tab with a unique URI to prevent state conflicts
                if (props.monaco) {
                    const uri = props.monaco.Uri.parse(`insight-${insight.short_id}-${Date.now()}`)
                    const model = props.monaco.editor.createModel(query, 'hogQL', uri)
                    props.editor?.setModel(model)

                    const mountedCodeEditorLogic =
                        codeEditorLogic.findMounted() ||
                        codeEditorLogic({
                            key: props.key,
                            query: values.sourceQuery?.source.query ?? '',
                            language: 'hogQL',
                        })

                    if (mountedCodeEditorLogic) {
                        initModel(model, mountedCodeEditorLogic)
                    }

                    const newTab: QueryTab = {
                        uri,
                        insight,
                        name: insight.name || 'Untitled',
                        sourceQuery: insight.query as DataVisualizationNode | undefined,
                    }

                    actions.addTab(newTab)
                    actions.selectTab(newTab)

                    // Set up the editor state
                    actions.setSourceQuery({
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query,
                        },
                        display: ChartDisplayType.ActionsTable,
                    })
                } else {
                    console.warn('Monaco not ready, falling back to createTab')
                    // Fallback to createTab if Monaco is not ready
                    actions.createTab(query, undefined, insight)
                }
            }
        },
        createTab: async ({ query = '', view, insight }) => {
            const mountedCodeEditorLogic =
                codeEditorLogic.findMounted() ||
                codeEditorLogic({
                    key: props.key,
                    query: values.sourceQuery?.source.query ?? '',
                    language: 'hogQL',
                })

            let currentModelCount = 1
            const allNumbers = values.allTabs.map((tab) => parseInt(tab.uri.path.split('/').pop() || '0'))
            while (allNumbers.includes(currentModelCount)) {
                currentModelCount++
            }

            const nextUntitledNumber = getNextUntitledNumber(values.allTabs)
            const tabName = view?.name || insight?.name || `${NEW_QUERY} ${nextUntitledNumber}`

            if (props.monaco) {
                // Use unique URI for insights to prevent state conflicts
                const uri = insight
                    ? props.monaco.Uri.parse(`insight-${insight.short_id}-${Date.now()}`)
                    : props.monaco.Uri.parse(currentModelCount.toString())
                const model = props.monaco.editor.createModel(query, 'hogQL', uri)
                props.editor?.setModel(model)

                if (mountedCodeEditorLogic) {
                    initModel(model, mountedCodeEditorLogic)
                }

                actions.addTab({
                    uri,
                    view,
                    insight,
                    name: tabName,
                    sourceQuery: insight?.query as DataVisualizationNode | undefined,
                })
                actions.selectTab({
                    uri,
                    view,
                    insight,
                    name: tabName,
                    sourceQuery: insight?.query as DataVisualizationNode | undefined,
                })

                // State is now managed by updateQueryTabState, no need to call setLocalState
            } else if (query) {
                // if navigating from URL without monaco loaded
                // State is now managed by updateQueryTabState, no need to call setLocalState
            }
        },
        renameTab: ({ tab, newName }) => {
            const updatedTabs = values.allTabs.map((t) => {
                if (t.uri.toString() === tab.uri.toString()) {
                    return {
                        ...t,
                        name: newName,
                    }
                }
                return t
            })
            actions.setTabs(updatedTabs)
            const activeTab = updatedTabs.find((t) => t.uri.toString() === tab.uri.toString())
            if (activeTab) {
                actions.selectTab(activeTab)
            }
            actions.updateState()
        },
        selectTab: ({ tab }) => {
            if (props.monaco) {
                const model = props.monaco.editor.getModel(tab.uri)
                props.editor?.setModel(model)
            }

            const path = tab.uri.path.split('/').pop()
            if (path) {
                actions.updateQueryTabState()
            }

            if (tab.insight) {
                actions.setActiveTab(OutputTab.Visualization)
            }
        },
        setSourceQuery: ({ sourceQuery }) => {
            if (!values.activeModelUri) {
                return
            }

            actions.updateTab({
                ...values.activeModelUri,
                sourceQuery,
            })
        },
        deleteTab: ({ tab: tabToRemove }) => {
            if (values.activeModelUri?.view && values.queryInput !== values.sourceQuery.source.query) {
                LemonDialog.open({
                    title: 'Close tab',
                    description: 'Are you sure you want to close this view? There are unsaved changes.',
                    primaryButton: {
                        children: 'Close without saving',
                        status: 'danger',
                        onClick: () => actions._deleteTab(tabToRemove),
                    },
                })
            } else if (values.updateInsightButtonEnabled) {
                LemonDialog.open({
                    title: 'Close insight',
                    description: 'Are you sure you want to close this insight? There are unsaved changes.',
                    primaryButton: {
                        children: 'Close without saving',
                        status: 'danger',
                        onClick: () => actions._deleteTab(tabToRemove),
                    },
                })
            } else if (values.queryInput !== '' && !values.activeModelUri?.view && !values.activeModelUri?.insight) {
                LemonDialog.open({
                    title: 'Unsaved query',
                    description:
                        "You're about to close a tab with an unsaved query. If you continue, your changes will be permanently lost.",
                    primaryButton: {
                        children: 'Close without saving',
                        status: 'danger',
                        onClick: () => actions._deleteTab(tabToRemove),
                    },
                })
            } else {
                actions._deleteTab(tabToRemove)
            }
        },
        _deleteTab: ({ tab: tabToRemove }) => {
            if (!props.monaco) {
                return
            }

            const model = props.monaco.editor.getModel(tabToRemove.uri)
            if (tabToRemove.uri.toString() === values.activeModelUri?.uri.toString()) {
                const indexOfModel = values.allTabs.findIndex(
                    (tab) => tab.uri.toString() === tabToRemove.uri.toString()
                )
                const nextModel =
                    values.allTabs[indexOfModel + 1] || values.allTabs[indexOfModel - 1] || values.allTabs[0] // there will always be one
                actions.selectTab(nextModel)
            }
            model?.dispose()
            actions.removeTab(tabToRemove)
            // State is now managed by updateQueryTabState, no need to call setLocalState
        },
        // setLocalState removed - now using database-only state management
        initialize: async () => {
            // Wait for queryTabState to be loaded before initializing
            if (!values.queryTabState) {
                console.warn('queryTabState not loaded, skipping initialization')
                return
            }

            const mountedCodeEditorLogic =
                codeEditorLogic.findMounted() ||
                codeEditorLogic({
                    key: props.key,
                    query: values.sourceQuery?.source.query ?? '',
                    language: 'hogQL',
                })

            // Parse the state from the database
            const state = values.queryTabState.state
            const allModelQueries = state.editorModelsStateKey ? JSON.parse(state.editorModelsStateKey) : []
            const activeModelUri = state.activeModelStateKey || ''

            if (allModelQueries && allModelQueries.length > 0) {
                // clear existing models
                props.monaco?.editor.getModels().forEach((model: editor.ITextModel) => {
                    model.dispose()
                })

                const newModels: QueryTab[] = []

                allModelQueries.forEach((model: Record<string, any>) => {
                    if (props.monaco) {
                        const uri = props.monaco.Uri.parse(model.path)
                        const newModel = props.monaco.editor.createModel(model.query, 'hogQL', uri)
                        props.editor?.setModel(newModel)

                        const existingTab = values.allTabs.find((tab) => tab.uri.path === uri.path)

                        newModels.push({
                            uri,
                            view: model.view,
                            insight: model.insight,
                            name: model.name,
                            sourceQuery: existingTab?.sourceQuery,
                            response: model.response,
                        })
                        mountedCodeEditorLogic && initModel(newModel, mountedCodeEditorLogic)
                    }
                })

                actions.setTabs(newModels)

                if (activeModelUri) {
                    const uri = props.monaco?.Uri.parse(activeModelUri)
                    const activeModel = props.monaco?.editor
                        .getModels()
                        .find((model: editor.ITextModel) => model.uri.path === uri?.path)
                    activeModel && props.editor?.setModel(activeModel)
                    const val = activeModel?.getValue()

                    if (val) {
                        actions.setQueryInput(val)
                    }

                    const activeTab = newModels.find((tab) => tab.uri.path.split('/').pop() === activeModelUri)
                    const activeView = activeTab?.view
                    const activeInsight = activeTab?.insight

                    if (uri && activeTab) {
                        actions.selectTab({
                            uri,
                            view: activeView,
                            name: activeView?.name || activeInsight?.name || activeTab.name,
                            insight: activeInsight,
                            sourceQuery: activeTab.sourceQuery,
                            response: activeTab.response,
                        })
                    }
                } else if (newModels.length) {
                    actions.selectTab({
                        uri: newModels[0].uri,
                        name: newModels[0].view?.name || newModels[0].insight?.name || newModels[0].name,
                        sourceQuery: newModels[0].sourceQuery,
                        view: newModels[0].view,
                        insight: newModels[0].insight,
                        response: newModels[0].response,
                    })
                }
            } else {
                const model = props.editor?.getModel()

                if (model) {
                    actions.createTab()
                }
            }
            actions.setCacheLoading(false)
        },
        setQueryInput: ({ queryInput }) => {
            // if editing a view, track latest history id changes are based on
            if (values.activeModelUri?.view && values.activeModelUri?.view.query?.query) {
                if (queryInput === values.activeModelUri.view?.query.query) {
                    actions.deleteInProgressViewEdit(values.activeModelUri.view.id)
                } else if (
                    !values.inProgressViewEdits[values.activeModelUri.view.id] &&
                    values.activeModelUri.view.latest_history_id
                ) {
                    actions.setInProgressViewEdit(
                        values.activeModelUri.view.id,
                        values.activeModelUri.view.latest_history_id
                    )
                }
            }
            actions.updateState()
        },
        updateState: async ({ skipBreakpoint }, breakpoint) => {
            if (skipBreakpoint !== true) {
                await breakpoint(100)
            }

            // Only update the database state, not local storage
            actions.updateQueryTabState(skipBreakpoint)
        },
        runQuery: ({ queryOverride, switchTab }) => {
            const query = queryOverride || values.queryInput

            const newSource = {
                ...values.sourceQuery.source,
                query,
                variables: Object.fromEntries(
                    Object.entries(values.sourceQuery.source.variables ?? {}).filter(([_, variable]) =>
                        query.includes(`{variables.${variable.code_name}}`)
                    )
                ),
            }

            actions.setSourceQuery({
                ...values.sourceQuery,
                source: newSource,
            })
            actions.setLastRunQuery({
                ...values.sourceQuery,
                source: newSource,
            })
            dataNodeLogic({
                key: values.dataLogicKey,
                query: newSource,
            }).mount()

            dataNodeLogic({
                key: values.dataLogicKey,
                query: newSource,
            }).actions.loadData(!switchTab ? 'force_async' : 'async')
        },
        saveAsView: async ({ materializeAfterSave = false }) => {
            LemonDialog.openForm({
                title: 'Save as view',
                initialValues: { viewName: values.activeModelUri?.name || '' },
                description: `View names can only contain letters, numbers, '_', or '$'. Spaces are not allowed.`,
                content: (isLoading) =>
                    isLoading ? (
                        <div className="h-[37px] flex items-center">
                            <ViewEmptyState />
                        </div>
                    ) : (
                        <LemonField name="viewName">
                            <LemonInput
                                data-attr="sql-editor-input-save-view-name"
                                disabled={isLoading}
                                placeholder="Please enter the name of the view"
                                autoFocus
                            />
                        </LemonField>
                    ),
                errors: {
                    viewName: (name) =>
                        !name
                            ? 'You must enter a name'
                            : !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)
                            ? 'Name must be valid'
                            : undefined,
                },
                onSubmit: async ({ viewName }) => {
                    await asyncActions.saveAsViewSubmit(viewName, materializeAfterSave)
                },
                shouldAwaitSubmit: true,
            })
        },
        saveAsViewSubmit: async ({ name, materializeAfterSave = false }) => {
            const query: HogQLQuery = values.sourceQuery.source

            const queryToSave = {
                ...query,
                query: values.queryInput,
            }

            const logic = dataNodeLogic({
                key: values.dataLogicKey,
                query: queryToSave,
            })

            const response = logic.values.response
            const types = response && 'types' in response ? response.types ?? [] : []
            try {
                await dataWarehouseViewsLogic.asyncActions.createDataWarehouseSavedQuery({
                    name,
                    query: queryToSave,
                    types,
                })

                actions.updateState()

                // Saved queries are unique by team,name
                const savedQuery = dataWarehouseViewsLogic.values.dataWarehouseSavedQueries.find((q) => q.name === name)

                if (materializeAfterSave && savedQuery) {
                    await dataWarehouseViewsLogic.asyncActions.updateDataWarehouseSavedQuery({
                        id: savedQuery.id,
                        sync_frequency: '24hour',
                        types: [[]],
                        lifecycle: 'create',
                    })
                }
            } catch {
                lemonToast.error('Failed to save view')
            }
        },
        saveAsInsight: async () => {
            LemonDialog.openForm({
                title: 'Save as new insight',
                initialValues: {
                    name: '',
                },
                content: (
                    <LemonField name="name">
                        <LemonInput data-attr="insight-name" placeholder="Please enter the new name" autoFocus />
                    </LemonField>
                ),
                errors: {
                    name: (name) => (!name ? 'You must enter a name' : undefined),
                },
                onSubmit: async ({ name }) => actions.saveAsInsightSubmit(name),
            })
        },
        saveAsInsightSubmit: async ({ name }) => {
            const insight = await insightsApi.create({
                name,
                query: values.sourceQuery,
                saved: true,
            })

            lemonToast.info(`You're now viewing ${insight.name || insight.derived_name || name}`)

            if (values.activeModelUri) {
                actions._deleteTab(values.activeModelUri)
            }

            router.actions.push(urls.insightView(insight.short_id))
        },
        updateInsight: async () => {
            if (!values.editingInsight) {
                return
            }

            const insightName = values.activeModelUri?.name

            const insightRequest: Partial<QueryBasedInsightModel> = {
                name: insightName ?? values.editingInsight.name,
                query: values.sourceQuery,
            }

            const savedInsight = await insightsApi.update(values.editingInsight.id, insightRequest)

            if (values.activeModelUri) {
                actions.updateTab({
                    ...values.activeModelUri,
                    insight: savedInsight,
                })
                actions.updateState(true)
            }

            lemonToast.info(`You're now viewing ${savedInsight.name || savedInsight.derived_name || name}`)

            if (values.activeModelUri) {
                actions._deleteTab(values.activeModelUri)
            }

            router.actions.push(urls.insightView(savedInsight.short_id))
        },
        loadDataWarehouseSavedQueriesSuccess: ({ dataWarehouseSavedQueries }) => {
            // keep tab views up to date
            const newTabs = values.allTabs.map((tab) => ({
                ...tab,
                view: dataWarehouseSavedQueries.find((v) => v.id === tab.view?.id),
            }))
            actions.setTabs(newTabs)
            actions.updateState()
        },
        deleteDataWarehouseSavedQuerySuccess: ({ payload: viewId }) => {
            const tabToRemove = values.allTabs.find((tab) => tab.view?.id === viewId)
            if (tabToRemove) {
                actions._deleteTab(tabToRemove)
            }
            lemonToast.success('View deleted')
        },
        createDataWarehouseSavedQuerySuccess: ({ dataWarehouseSavedQueries, payload: view }) => {
            const newView = view && dataWarehouseSavedQueries.find((v) => v.name === view.name)
            if (newView) {
                const newTabs = values.allTabs.map((tab) => ({
                    ...tab,
                    view: tab.uri.path === values.activeModelUri?.uri.path ? newView : tab.view,
                }))
                const newTab = newTabs.find((tab) => tab.uri.path === values.activeModelUri?.uri.path)
                actions.setTabs(newTabs)
                newTab && actions.selectTab(newTab)
                actions.updateState()
            }
        },
        updateDataWarehouseSavedQuerySuccess: ({ dataWarehouseSavedQueries }) => {
            // // check if the active tab is a view and if so, update the view
            const activeTab = dataWarehouseSavedQueries.find((tab) => tab.id === values.activeModelUri?.view?.id)
            if (activeTab && values.activeModelUri) {
                actions.selectTab({
                    ...values.activeModelUri,
                    view: activeTab,
                })
            }
            lemonToast.success('View updated')
        },
        updateQueryTabState: async ({ skipBreakpoint }, breakpoint) => {
            if (skipBreakpoint !== true) {
                await breakpoint(1000)
            }

            if (!values.queryTabState) {
                return
            }
            try {
                // Build the state data directly from current state instead of reading from local storage
                const queries = values.allTabs.map((model) => {
                    return {
                        query: props.monaco?.editor.getModel(model.uri)?.getValue() || '',
                        path: model.uri.path.split('/').pop(),
                        name: model.view?.name || model.name,
                        view: model.view,
                        insight: model.insight,
                        response: model.response,
                    }
                })

                const activeModelUri = values.activeModelUri?.uri.path.split('/').pop() || ''

                await api.queryTabState.update(values.queryTabState.id, {
                    state: {
                        editorModelsStateKey: JSON.stringify(queries),
                        activeModelStateKey: activeModelUri,
                        sourceQuery: JSON.stringify(values.sourceQuery),
                    },
                })
            } catch (e) {
                console.error(e)
            }
        },
        setResponse: ({ response, currentTab }) => {
            if (!currentTab || !response) {
                return
            }

            const responseInBytes = sizeOfInBytes(response)

            // Store in local storage if the response is less than 1 MB
            if (responseInBytes <= 1024 * 1024) {
                actions.updateTab({
                    ...currentTab,
                    response,
                })
            }
        },
        updateView: async ({ view }) => {
            const latestView = await api.dataWarehouseSavedQueries.get(view.id)
            if (
                view.edited_history_id !== latestView?.latest_history_id &&
                view.query?.query !== latestView?.query.query
            ) {
                actions._setSuggestionPayload({
                    originalValue: latestView?.query.query,
                    acceptText: 'Confirm changes',
                    rejectText: 'Cancel',
                    diffShowRunButton: false,
                    onAccept: () => {
                        actions.setQueryInput(view.query?.query ?? '')
                        actions.updateDataWarehouseSavedQuery({
                            ...view,
                            edited_history_id: latestView?.latest_history_id,
                        })
                    },
                    onReject: () => {},
                })
                lemonToast.error('View has been edited by another user. Review changes to update.')
            } else {
                actions.updateDataWarehouseSavedQuery(view)
            }
        },
    })),
    subscriptions(({ props, actions, values }) => ({
        showLegacyFilters: (showLegacyFilters: boolean) => {
            if (showLegacyFilters) {
                actions.setSourceQuery({
                    ...values.sourceQuery,
                    source: {
                        ...values.sourceQuery.source,
                        filters: {},
                    },
                })
            } else {
                actions.setSourceQuery({
                    ...values.sourceQuery,
                    source: {
                        ...values.sourceQuery.source,
                        filters: undefined,
                    },
                })
            }
        },
        activeModelUri: (activeModelUri) => {
            if (props.monaco) {
                const _model = props.monaco.editor.getModel(activeModelUri.uri)
                const val = _model?.getValue()
                actions.setQueryInput(val ?? '')
                if (activeModelUri.sourceQuery) {
                    actions.setSourceQuery({
                        ...activeModelUri.sourceQuery,
                        source: {
                            ...activeModelUri.sourceQuery.source,
                            query: val ?? '',
                        },
                    })
                } else {
                    actions.setSourceQuery({
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: val ?? '',
                        },
                        display: ChartDisplayType.ActionsLineGraph,
                    })
                }
            }
        },
        allTabs: () => {
            // keep selected tab up to date
            const activeTab = values.allTabs.find((tab) => tab.uri.path === values.activeModelUri?.uri.path)
            if (activeTab && activeTab.uri.path != values.activeModelUri?.uri.path) {
                actions.selectTab(activeTab)
            }
        },
        editingView: (editingView) => {
            if (editingView) {
                actions.resetDataModelingJobs()
                actions.loadDataModelingJobs(editingView.id)
                actions.loadUpstream(editingView.id)
            }
        },
        queryTabState: (queryTabState) => {
            // Initialize after queryTabState is loaded
            if (queryTabState && props.monaco && props.editor) {
                actions.initialize()
            }
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
                if (suggestionPayload?.suggestedValue && suggestionPayload?.suggestedValue !== queryInput) {
                    return queryInput
                }

                if (suggestionPayload?.originalValue && suggestionPayload?.originalValue !== queryInput) {
                    return suggestionPayload?.originalValue
                }

                return undefined
            },
        ],
        editingView: [
            (s) => [s.activeModelUri],
            (activeModelUri) => {
                return activeModelUri?.view
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
        isEditingMaterializedView: [
            (s) => [s.editingView],
            (editingView) => {
                return !!editingView?.status
            },
        ],
        isSourceQueryLastRun: [
            (s) => [s.queryInput, s.lastRunQuery],
            (queryInput, lastRunQuery) => {
                return queryInput === lastRunQuery?.source.query
            },
        ],
        updateInsightButtonEnabled: [
            (s) => [s.sourceQuery, s.activeModelUri],
            (sourceQuery, activeModelUri) => {
                if (!activeModelUri?.insight?.query || !activeModelUri.sourceQuery) {
                    return false
                }

                const updatedName = activeModelUri.name !== activeModelUri.insight.name

                const sourceQueryWithoutUndefinedAndNullKeys = removeUndefinedAndNull(sourceQuery)

                return (
                    updatedName ||
                    !isEqual(
                        sourceQueryWithoutUndefinedAndNullKeys,
                        removeUndefinedAndNull(activeModelUri.insight.query)
                    )
                )
            },
        ],
        showLegacyFilters: [
            (s) => [s.queryInput],
            (queryInput) => {
                return queryInput.indexOf('{filters}') !== -1 || queryInput.indexOf('{filters.') !== -1
            },
        ],
        dataLogicKey: [
            (s) => [s.activeModelUri, s.editingInsight],
            (activeModelUri, editingInsight) => {
                if (editingInsight) {
                    return `InsightViz.${editingInsight.short_id}`
                }

                return (
                    activeModelUri?.uri.path ??
                    insightVizDataNodeKey({
                        dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
                        cachedInsight: null,
                        doNotLoad: true,
                    })
                )
            },
        ],
        localStorageResponse: [
            (s) => [s.activeModelUri],
            (activeModelUri) => {
                return activeModelUri?.response
            },
        ],
    }),
    urlToAction(({ actions, props }) => ({
        [urls.sqlEditor()]: async (_, searchParams) => {
            if (!searchParams.open_query && !searchParams.open_view && !searchParams.open_insight) {
                return
            }

            // Wait for Monaco to be ready before proceeding
            if (!props.monaco) {
                console.warn('Monaco not ready, skipping URL parameter handling')
                return
            }

            let tabAdded = false

            const createQueryTab = async (): Promise<void> => {
                if (searchParams.open_view) {
                    const view = dataWarehouseViewsLogic.values.dataWarehouseSavedQueryMapById[searchParams.open_view]
                    if (view) {
                        const queryToOpen = searchParams.open_query ? searchParams.open_query : view.query.query
                        actions.editView(queryToOpen, view)
                        tabAdded = true
                    }
                } else if (searchParams.open_insight) {
                    if (searchParams.open_insight === 'new') {
                        // Add new blank tab
                        actions.createTab()
                        router.actions.replace(router.values.location.pathname)
                        return
                    }

                    try {
                        // Load insight data first
                        const shortId = searchParams.open_insight
                        const insight = await insightsApi.getByShortId(shortId, undefined, 'async')
                        if (!insight) {
                            lemonToast.error('Insight not found')
                            return
                        }

                        // Get the query from the insight
                        let query = ''
                        if (insight.query?.kind === NodeKind.DataVisualizationNode) {
                            query = (insight.query as DataVisualizationNode).source.query
                        }

                        // Use the editInsight action to properly handle tab creation and state management
                        actions.editInsight(query, insight)
                        tabAdded = true
                    } catch (error) {
                        lemonToast.error('Failed to load insight')
                        console.error(error)
                    }
                } else if (searchParams.open_query) {
                    actions.createTab(searchParams.open_query)
                    tabAdded = true
                }
            }

            await createQueryTab()

            if (tabAdded) {
                router.actions.replace(router.values.location.pathname)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadQueryTabState()
    }),
])
