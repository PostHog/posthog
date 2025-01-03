import { Monaco } from '@monaco-editor/react'
import { LemonDialog, LemonInput, lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { initModel } from 'lib/monaco/CodeEditor'
import { codeEditorLogic } from 'lib/monaco/codeEditorLogic'
import { editor, Uri } from 'monaco-editor'
import { insightsApi } from 'scenes/insights/utils/api'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import { HogQLMetadataResponse, HogQLQuery, NodeKind } from '~/queries/schema'
import { DataVisualizationNode } from '~/queries/schema'
import { DataWarehouseSavedQuery, ExportContext } from '~/types'

import { DATAWAREHOUSE_EDITOR_ITEM_ID } from '../external/dataWarehouseExternalSceneLogic'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import type { multitabEditorLogicType } from './multitabEditorLogicType'

export const dataNodeKey = insightVizDataNodeKey({
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

export interface QueryTab {
    uri: Uri
    view?: DataWarehouseSavedQuery
}

export const multitabEditorLogic = kea<multitabEditorLogicType>([
    path(['data-warehouse', 'editor', 'multitabEditorLogic']),
    props({} as MultitabEditorLogicProps),
    key((props) => props.key),
    connect({
        actions: [
            dataWarehouseViewsLogic,
            [
                'loadDataWarehouseSavedQueriesSuccess',
                'deleteDataWarehouseSavedQuerySuccess',
                'createDataWarehouseSavedQuerySuccess',
                'runDataWarehouseSavedQuery',
            ],
        ],
    }),
    actions({
        setQueryInput: (queryInput: string) => ({ queryInput }),
        updateState: true,
        runQuery: (queryOverride?: string, switchTab?: boolean) => ({ queryOverride, switchTab }),
        setActiveQuery: (query: string) => ({ query }),
        setTabs: (tabs: QueryTab[]) => ({ tabs }),
        addTab: (tab: QueryTab) => ({ tab }),
        createTab: (query?: string, view?: DataWarehouseSavedQuery) => ({ query, view }),
        deleteTab: (tab: QueryTab) => ({ tab }),
        removeTab: (tab: QueryTab) => ({ tab }),
        selectTab: (tab: QueryTab) => ({ tab }),
        setLocalState: (key: string, value: any) => ({ key, value }),
        initialize: true,
        saveAsView: true,
        saveAsViewSubmit: (name: string) => ({ name }),
        saveAsInsight: true,
        saveAsInsightSubmit: (name: string) => ({ name }),
        setCacheLoading: (loading: boolean) => ({ loading }),
        setError: (error: string | null) => ({ error }),
        setIsValidView: (isValidView: boolean) => ({ isValidView }),
        setSourceQuery: (sourceQuery: DataVisualizationNode) => ({ sourceQuery }),
        setMetadata: (metadata: HogQLMetadataResponse | null) => ({ metadata }),
        setMetadataLoading: (loading: boolean) => ({ loading }),
        editView: (query: string, view: DataWarehouseSavedQuery) => ({ query, view }),
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (!oldProps.monaco && !oldProps.editor && props.monaco && props.editor) {
            actions.initialize()
        }
    }),
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
            } as DataVisualizationNode,
            {
                setSourceQuery: (_, { sourceQuery }) => sourceQuery,
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
        allTabs: [
            [] as QueryTab[],
            {
                addTab: (state, { tab }) => {
                    const newTabs = [...state, tab]
                    return newTabs
                },
                removeTab: (state, { tab: tabToRemove }) => {
                    const newModels = state.filter((tab) => tab.uri.toString() !== tabToRemove.uri.toString())
                    return newModels
                },
                setTabs: (_, { tabs }) => tabs,
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
        createTab: ({ query = '', view }) => {
            const mountedCodeEditorLogic = codeEditorLogic.findMounted()
            let currentModelCount = 1
            const allNumbers = values.allTabs.map((tab) => parseInt(tab.uri.path.split('/').pop() || '0'))
            while (allNumbers.includes(currentModelCount)) {
                currentModelCount++
            }

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
                })
                actions.selectTab({
                    uri,
                    view,
                })

                const queries = values.allTabs.map((tab) => {
                    return {
                        query: props.monaco?.editor.getModel(tab.uri)?.getValue() || '',
                        path: tab.uri.path.split('/').pop(),
                        view: uri.path === tab.uri.path ? view : tab.view,
                    }
                })
                actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        selectTab: ({ tab }) => {
            if (props.monaco) {
                const model = props.monaco.editor.getModel(tab.uri)
                props.editor?.setModel(model)
            }

            const path = tab.uri.path.split('/').pop()
            path && actions.setLocalState(activeModelStateKey(props.key), path)
        },
        deleteTab: ({ tab: tabToRemove }) => {
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
                    }
                })
                actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        setLocalState: ({ key, value }) => {
            localStorage.setItem(key, value)
        },
        initialize: () => {
            const allModelQueries = localStorage.getItem(editorModelsStateKey(props.key))
            const activeModelUri = localStorage.getItem(activeModelStateKey(props.key))
            const activeModelVariablesString = localStorage.getItem(activeModelVariablesStateKey(props.key))
            const activeModelVariables =
                activeModelVariablesString && activeModelVariablesString != 'undefined'
                    ? JSON.parse(activeModelVariablesString)
                    : {}

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
                        newModels.push({
                            uri,
                            view: model.view,
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
                        actions.setSourceQuery({
                            ...values.sourceQuery,
                            source: {
                                ...values.sourceQuery.source,
                                variables: activeModelVariables,
                            },
                        })
                        actions.setQueryInput(val)
                        actions.runQuery()
                    }
                    const activeView = newModels.find((tab) => tab.uri.path.split('/').pop() === activeModelUri)?.view

                    uri &&
                        actions.selectTab({
                            uri,
                            view: activeView,
                        })
                } else if (newModels.length) {
                    actions.selectTab({
                        uri: newModels[0].uri,
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
        updateState: async (_, breakpoint) => {
            await breakpoint(100)
            const queries = values.allTabs.map((model) => {
                return {
                    query: props.monaco?.editor.getModel(model.uri)?.getValue() || '',
                    path: model.uri.path.split('/').pop(),
                    view: model.view,
                }
            })
            localStorage.setItem(editorModelsStateKey(props.key), JSON.stringify(queries))
        },
        setSourceQuery: ({ sourceQuery }) => {
            // NOTE: this is a hack to get the variables to persist.
            // Variables should be handled first in this logic and then in the downstream variablesLogic
            localStorage.setItem(activeModelVariablesStateKey(props.key), JSON.stringify(sourceQuery.source.variables))
        },
        runQuery: ({ queryOverride, switchTab }) => {
            const query = queryOverride || values.queryInput

            actions.setSourceQuery({
                ...values.sourceQuery,
                source: {
                    ...values.sourceQuery.source,
                    query,
                },
            })
            dataNodeLogic({
                key: dataNodeKey,
                query: {
                    ...values.sourceQuery.source,
                    query,
                },
                autoLoad: false,
            }).actions.loadData(!switchTab)
        },
        saveAsView: async () => {
            LemonDialog.openForm({
                title: 'Save as view',
                initialValues: { viewName: '' },
                content: (
                    <LemonField name="viewName">
                        <LemonInput placeholder="Please enter the name of the view" autoFocus />
                    </LemonField>
                ),
                errors: {
                    viewName: (name) => (!name ? 'You must enter a name' : undefined),
                },
                onSubmit: async ({ viewName }) => {
                    await asyncActions.saveAsViewSubmit(viewName)
                },
                shouldAwaitSubmit: true,
            })
        },
        saveAsViewSubmit: async ({ name }) => {
            const query: HogQLQuery = values.sourceQuery.source

            const logic = dataNodeLogic({
                key: dataNodeKey,
                query,
            })

            const types = logic.values.response?.types ?? []

            await dataWarehouseViewsLogic.asyncActions.createDataWarehouseSavedQuery({ name, query, types })
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
                actions.deleteTab(tabToRemove)
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
    })),
    subscriptions(({ props, actions, values }) => ({
        activeModelUri: (activeModelUri) => {
            if (props.monaco) {
                const _model = props.monaco.editor.getModel(activeModelUri.uri)
                const val = _model?.getValue()
                actions.setQueryInput(val ?? '')
                actions.runQuery(undefined, true)
            }
        },
        allTabs: () => {
            // keep selected tab up to date
            const activeTab = values.allTabs.find((tab) => tab.uri.path === values.activeModelUri?.uri.path)
            activeTab && actions.selectTab(activeTab)
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
    }),
])
