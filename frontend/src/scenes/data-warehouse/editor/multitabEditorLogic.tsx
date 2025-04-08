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
import isEqual from 'lodash.isequal'
import { editor, Uri } from 'monaco-editor'
import { insightsApi } from 'scenes/insights/utils/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import { DataVisualizationNode, HogQLMetadataResponse, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    DataWarehouseSavedQuery,
    ExportContext,
    QueryBasedInsightModel,
    QueryTabState,
} from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { DATAWAREHOUSE_EDITOR_ITEM_ID } from '../utils'
import type { multitabEditorLogicType } from './multitabEditorLogicType'
import { outputPaneLogic, OutputTab } from './outputPaneLogic'
import { ViewEmptyState } from './ViewLoadingState'

const dataNodeKey = insightVizDataNodeKey({
    dashboardItemId: DATAWAREHOUSE_EDITOR_ITEM_ID,
    cachedInsight: null,
    doNotLoad: true,
})

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

export interface QueryTab {
    uri: Uri
    view?: DataWarehouseSavedQuery
    name: string
    sourceQuery?: DataVisualizationNode
    insight?: QueryBasedInsightModel
}

export const multitabEditorLogic = kea<multitabEditorLogicType>([
    path(['data-warehouse', 'editor', 'multitabEditorLogic']),
    props({} as MultitabEditorLogicProps),
    key((props) => props.key),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries'], userLogic, ['user']],
        actions: [
            dataWarehouseViewsLogic,
            [
                'loadDataWarehouseSavedQueriesSuccess',
                'deleteDataWarehouseSavedQuerySuccess',
                'createDataWarehouseSavedQuerySuccess',
                'runDataWarehouseSavedQuery',
            ],
            outputPaneLogic,
            ['setActiveTab'],
        ],
    })),
    actions({
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
        setIsValidView: (isValidView: boolean) => ({ isValidView }),
        setSourceQuery: (sourceQuery: DataVisualizationNode) => ({ sourceQuery }),
        setMetadata: (metadata: HogQLMetadataResponse | null) => ({ metadata }),
        setMetadataLoading: (loading: boolean) => ({ loading }),
        editView: (query: string, view: DataWarehouseSavedQuery) => ({ query, view }),
        editInsight: (query: string, insight: QueryBasedInsightModel) => ({ query, insight }),
        updateQueryTabState: (skipBreakpoint?: boolean) => ({ skipBreakpoint }),
        setLastRunQuery: (lastRunQuery: DataVisualizationNode | null) => ({ lastRunQuery }),
    }),
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

                    const localEditorModels = localStorage.getItem(editorModelsStateKey(props.key))
                    const localActiveModelUri = localStorage.getItem(activeModelStateKey(props.key))

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
        editingView: [
            null as DataWarehouseSavedQuery | null,
            {
                selectTab: (_, { tab }) => tab.view ?? null,
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
        isValidView: [
            false,
            {
                setIsValidView: (_, { isValidView }) => isValidView,
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
    })),
    listeners(({ values, props, actions, asyncActions }) => ({
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
                actions.selectTab(maybeExistingTab)
            } else {
                actions.createTab(query, undefined, insight)
            }
        },
        createTab: ({ query = '', view, insight }) => {
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
            if (props.monaco) {
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
                    }
                })
                actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        setLocalState: ({ key, value }) => {
            localStorage.setItem(key, value)
        },
        initialize: () => {
            // TODO: replace with queryTabState
            const allModelQueries = localStorage.getItem(editorModelsStateKey(props.key))
            const activeModelUri = localStorage.getItem(activeModelStateKey(props.key))

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
                        })
                    }
                } else if (newModels.length) {
                    actions.selectTab({
                        uri: newModels[0].uri,
                        name: newModels[0].view?.name || newModels[0].insight?.name || newModels[0].name,
                        sourceQuery: newModels[0].sourceQuery,
                        view: newModels[0].view,
                        insight: newModels[0].insight,
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
        setQueryInput: () => {
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

            const types = logic.values.response?.types ?? []
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
            router.actions.push(urls.insightView(savedInsight.short_id, undefined, undefined))
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
        updateDataWarehouseSavedQuerySuccess: () => {
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
                        editorModelsStateKey: localStorage.getItem(editorModelsStateKey(props.key)),
                        activeModelStateKey: localStorage.getItem(activeModelStateKey(props.key)),
                        sourceQuery: JSON.stringify(values.sourceQuery),
                    },
                })
            } catch (e) {
                console.error(e)
            }
        },
    })),
    subscriptions(({ props, actions, values }) => ({
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
    })),
    selectors({
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
            (s) => [s.sourceQuery],
            (sourceQuery) => {
                return sourceQuery.source.query.indexOf('{filters}') !== -1
            },
        ],
        dataLogicKey: [
            (s) => [s.activeModelUri, s.editingInsight],
            (activeModelUri, editingInsight) => {
                if (editingInsight) {
                    return `InsightViz.${editingInsight.short_id}`
                }

                return activeModelUri?.uri.path ?? dataNodeKey
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
                if (searchParams.open_query) {
                    // Open query string
                    actions.createTab(searchParams.open_query)
                    tabAdded = true
                    router.actions.replace(router.values.location.pathname)
                } else if (searchParams.open_view) {
                    // Open view
                    const viewId = searchParams.open_view
                    const view = values.dataWarehouseSavedQueries.find((n) => n.id === viewId)
                    if (!view) {
                        lemonToast.error('View not found')
                        return
                    }

                    actions.editView(view.query.query, view)
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

                    actions.editInsight(query, insight)
                    actions.runQuery()
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
