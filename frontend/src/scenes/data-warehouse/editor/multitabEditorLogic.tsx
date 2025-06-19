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
import { get, set } from './db'
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

export const editorModelsStateKey = (key: string | number): string => `${key}/editorModelQueries`
export const activeModelStateKey = (key: string | number): string => `${key}/activeModelUri`
export const activeModelVariablesStateKey = (key: string | number): string => `${key}/activeModelVariables`

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

const getStorageItem = async (key: string): Promise<string | null> => {
    const dbValue = await get(key)

    if (dbValue) {
        return dbValue
    }

    const lsValue = localStorage.getItem(key)

    if (lsValue) {
        await set(key, lsValue)
        localStorage.removeItem(key)
        return lsValue
    }

    return null
}

const setStorageItem = async (key: string, value: string): Promise<void> => {
    await set(key, value)
}

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
        setLocalState: (key: string, value: any) => ({ key, value }),
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
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps.monaco && !oldProps.editor && props.monaco && props.editor) {
            actions.initialize()
        }
    }),
    loaders(({ values, props }) => ({
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

                    const localEditorModels = await getStorageItem(editorModelsStateKey(props.key))
                    const localActiveModelUri = await getStorageItem(activeModelStateKey(props.key))

                    if (queryTabStateModel === null) {
                        queryTabStateModel = await api.queryTabState.create({
                            state: {
                                editorModelsStateKey: localEditorModels || '',
                                activeModelStateKey: localActiveModelUri || '',
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
                actions.createTab(query, undefined, insight)
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
                const uri = props.monaco.Uri.parse(currentModelCount.toString())
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

                const queries = values.allTabs.map((tab) => {
                    return {
                        query: props.monaco?.editor.getModel(tab.uri)?.getValue() || '',
                        path: tab.uri.path.split('/').pop(),
                        view: uri.path === tab.uri.path ? view : tab.view,
                        insight: uri.path === tab.uri.path ? insight : tab.insight,
                        sourceQuery: uri.path === tab.uri.path ? insight?.query : tab.insight?.query,
                        name: tab.name,
                        response: tab.response,
                    }
                })
                actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            } else if (query) {
                // if navigating from URL without monaco loaded
                const queries = [
                    ...values.allTabs,
                    {
                        query,
                        path: currentModelCount.toString(),
                        view,
                        insight,
                        name: tabName,
                        sourceQuery: insight?.query as DataVisualizationNode | undefined,
                    },
                ]
                actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
                actions.setLocalState(activeModelStateKey(props.key), currentModelCount.toString())
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
                actions.setLocalState(activeModelStateKey(props.key), path)
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
            const queries = values.allTabs.map((tab) => {
                return {
                    query: props.monaco?.editor.getModel(tab.uri)?.getValue() || '',
                    path: tab.uri.path.split('/').pop(),
                    view: tab.view,
                    insight: tab.insight,
                    response: tab.response,
                }
            })
            actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
        },
        setLocalState: async ({ key, value }) => {
            await setStorageItem(key, value)
        },
        initialize: async () => {
            // TODO: replace with queryTabState
            const allModelQueries = await getStorageItem(editorModelsStateKey(props.key))
            const activeModelUri = await getStorageItem(activeModelStateKey(props.key))

            const mountedCodeEditorLogic =
                codeEditorLogic.findMounted() ||
                codeEditorLogic({
                    key: props.key,
                    query: values.sourceQuery?.source.query ?? '',
                    language: 'hogQL',
                })

            if (allModelQueries) {
                // clear existing models
                props.monaco?.editor.getModels().forEach((model: editor.ITextModel) => {
                    model.dispose()
                })

                const models = JSON.parse(allModelQueries || '[]')
                const newModels: QueryTab[] = []

                models.forEach((model: Record<string, any>) => {
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
            actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
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
            } catch (e) {
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
                await api.queryTabState.update(values.queryTabState.id, {
                    state: {
                        editorModelsStateKey: await getStorageItem(editorModelsStateKey(props.key)),
                        activeModelStateKey: await getStorageItem(activeModelStateKey(props.key)),
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
    urlToAction(({ actions, values, props }) => ({
        [urls.sqlEditor()]: async (_, searchParams) => {
            if (!searchParams.open_query && !searchParams.open_view && !searchParams.open_insight) {
                return
            }

            let tabAdded = false

            const createQueryTab = async (): Promise<void> => {
                if (searchParams.open_view) {
                    // Open view
                    const viewId = searchParams.open_view

                    if (values.dataWarehouseSavedQueries.length === 0) {
                        await dataWarehouseViewsLogic.asyncActions.loadDataWarehouseSavedQueries()
                    }

                    const view = values.dataWarehouseSavedQueries.find((n) => n.id === viewId)
                    if (!view) {
                        lemonToast.error('View not found')
                        return
                    }

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : view.query.query

                    actions.editView(queryToOpen, view)
                    tabAdded = true
                    router.actions.replace(router.values.location.pathname)
                } else if (searchParams.open_insight) {
                    if (searchParams.open_insight === 'new') {
                        // Add new blank tab
                        actions.createTab()
                        tabAdded = true
                        router.actions.replace(router.values.location.pathname)
                        return
                    }

                    // Open Insight
                    const shortId = searchParams.open_insight
                    const insight = await insightsApi.getByShortId(shortId, undefined, 'async')
                    if (!insight) {
                        lemonToast.error('Insight not found')
                        return
                    }

                    let query = ''
                    if (insight.query?.kind === NodeKind.DataVisualizationNode) {
                        query = (insight.query as DataVisualizationNode).source.query
                    }

                    const queryToOpen = searchParams.open_query ? searchParams.open_query : query

                    actions.editInsight(queryToOpen, insight)

                    // Only run the query if the results aren't already cached locally and we're not using the open_query search param
                    if (
                        insight.query?.kind === NodeKind.DataVisualizationNode &&
                        insight.query &&
                        !searchParams.open_query
                    ) {
                        dataNodeLogic({
                            key: values.dataLogicKey,
                            query: (insight.query as DataVisualizationNode).source,
                        }).mount()

                        const response = dataNodeLogic({
                            key: values.dataLogicKey,
                            query: (insight.query as DataVisualizationNode).source,
                        }).values.response

                        if (!response) {
                            actions.runQuery()
                        }
                    } else {
                        actions.runQuery()
                    }

                    tabAdded = true
                    router.actions.replace(router.values.location.pathname)
                } else if (searchParams.open_query) {
                    // Open query string
                    actions.createTab(searchParams.open_query)
                    tabAdded = true
                    router.actions.replace(router.values.location.pathname)
                }
            }

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

            await waitUntilMonaco().then(async () => {
                await createQueryTab()
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadQueryTabState()
    }),
])
