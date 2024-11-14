import { Monaco } from '@monaco-editor/react'
import { LemonDialog, LemonInput } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ModelMarker } from 'lib/monaco/codeEditorLogic'
import { editor, MarkerSeverity, Uri } from 'monaco-editor'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { HogLanguage, HogQLMetadata, HogQLMetadataResponse, HogQLNotice, HogQLQuery, NodeKind } from '~/queries/schema'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import type { multitabEditorLogicType } from './multitabEditorLogicType'

export interface MultitabEditorLogicProps {
    key: string
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

export const editorModelsStateKey = (key: string | number): string => `${key}/editorModelQueries`
export const activemodelStateKey = (key: string | number): string => `${key}/activeModelUri`

export const multitabEditorLogic = kea<multitabEditorLogicType>([
    path(['data-warehouse', 'editor', 'multitabEditorLogic']),
    props({} as MultitabEditorLogicProps),
    actions({
        setQueryInput: (queryInput: string) => ({ queryInput }),
        updateState: true,
        runQuery: (queryOverride?: string) => ({ queryOverride }),
        setActiveQuery: (query: string) => ({ query }),
        setTabs: (tabs: Uri[]) => ({ tabs }),
        addTab: (tab: Uri) => ({ tab }),
        createTab: () => null,
        deleteTab: (tab: Uri) => ({ tab }),
        removeTab: (tab: Uri) => ({ tab }),
        selectTab: (tab: Uri) => ({ tab }),
        setLocalState: (key: string, value: any) => ({ key, value }),
        initialize: true,
        saveAsView: true,
        saveAsViewSuccess: (name: string) => ({ name }),
        reloadMetadata: true,
        setMetadata: (query: string, metadata: HogQLMetadataResponse) => ({ query, metadata }),
    }),
    propsChanged(({ actions }, oldProps) => {
        if (!oldProps.monaco && !oldProps.editor) {
            actions.initialize()
        }
    }),
    reducers(({ props }) => ({
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
            null as Uri | null,
            {
                selectTab: (_, { tab }) => tab,
            },
        ],
        allTabs: [
            [] as Uri[],
            {
                addTab: (state, { tab }) => {
                    const newTabs = [...state, tab]
                    return newTabs
                },
                removeTab: (state, { tab: tabToRemove }) => {
                    const newModels = state.filter((tab) => tab.toString() !== tabToRemove.toString())
                    return newModels
                },
                setTabs: (_, { tabs }) => tabs,
            },
        ],
        metadata: [
            null as null | [string, HogQLMetadataResponse],
            {
                setMetadata: (_, { query, metadata }) => [query, metadata],
            },
        ],
        modelMarkers: [
            [] as ModelMarker[],
            {
                setMetadata: (_, { query, metadata }) => {
                    const model = props.editor?.getModel()
                    if (!model || !metadata) {
                        return []
                    }
                    const markers: ModelMarker[] = []
                    const metadataResponse = metadata

                    function noticeToMarker(error: HogQLNotice, severity: MarkerSeverity): ModelMarker {
                        const start = model!.getPositionAt(error.start ?? 0)
                        const end = model!.getPositionAt(error.end ?? query.length)
                        return {
                            start: error.start ?? 0,
                            startLineNumber: start.lineNumber,
                            startColumn: start.column,
                            end: error.end ?? query.length,
                            endLineNumber: end.lineNumber,
                            endColumn: end.column,
                            message: error.message ?? 'Unknown error',
                            severity: severity,
                            hogQLFix: error.fix,
                        }
                    }

                    for (const notice of metadataResponse?.errors ?? []) {
                        markers.push(noticeToMarker(notice, 8 /* MarkerSeverity.Error */))
                    }
                    for (const notice of metadataResponse?.warnings ?? []) {
                        markers.push(noticeToMarker(notice, 4 /* MarkerSeverity.Warning */))
                    }
                    for (const notice of metadataResponse?.notices ?? []) {
                        markers.push(noticeToMarker(notice, 1 /* MarkerSeverity.Hint */))
                    }

                    props.monaco?.editor.setModelMarkers(model, 'hogql', markers)
                    return markers
                },
            },
        ],
    })),
    listeners(({ values, props, actions }) => ({
        createTab: () => {
            let currentModelCount = 1
            const allNumbers = values.allTabs.map((tab) => parseInt(tab.path.split('/').pop() || '0'))
            while (allNumbers.includes(currentModelCount)) {
                currentModelCount++
            }

            if (props.monaco) {
                const uri = props.monaco.Uri.parse(currentModelCount.toString())
                const model = props.monaco.editor.createModel('', 'hogQL', uri)
                props.editor?.setModel(model)
                actions.addTab(uri)
                actions.selectTab(uri)

                const queries = values.allTabs.map((tab) => {
                    return {
                        query: props.monaco?.editor.getModel(tab)?.getValue() || '',
                        path: tab.path.split('/').pop(),
                    }
                })
                actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        selectTab: ({ tab }) => {
            if (props.monaco) {
                const model = props.monaco.editor.getModel(tab)
                props.editor?.setModel(model)
            }

            const path = tab.path.split('/').pop()
            path && actions.setLocalState(activemodelStateKey(props.key), path)
        },
        deleteTab: ({ tab: tabToRemove }) => {
            if (props.monaco) {
                const model = props.monaco.editor.getModel(tabToRemove)
                if (tabToRemove == values.activeModelUri) {
                    const indexOfModel = values.allTabs.findIndex((tab) => tab.toString() === tabToRemove.toString())
                    const nextModel =
                        values.allTabs[indexOfModel + 1] || values.allTabs[indexOfModel - 1] || values.allTabs[0] // there will always be one
                    actions.selectTab(nextModel)
                }
                model?.dispose()
                actions.removeTab(tabToRemove)
                const queries = values.allTabs.map((tab) => {
                    return {
                        query: props.monaco?.editor.getModel(tab)?.getValue() || '',
                        path: tab.path.split('/').pop(),
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
            const activeModelUri = localStorage.getItem(activemodelStateKey(props.key))

            if (allModelQueries) {
                // clear existing models
                props.monaco?.editor.getModels().forEach((model: editor.ITextModel) => {
                    model.dispose()
                })

                const models = JSON.parse(allModelQueries || '[]')
                const newModels: Uri[] = []

                models.forEach((model: Record<string, any>) => {
                    if (props.monaco) {
                        const uri = props.monaco.Uri.parse(model.path)
                        const newModel = props.monaco.editor.createModel(model.query, 'hogQL', uri)
                        props.editor?.setModel(newModel)
                        newModels.push(uri)
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
                        actions.runQuery()
                    }
                    uri && actions.selectTab(uri)
                } else if (newModels.length) {
                    actions.selectTab(newModels[0])
                }
            } else {
                const model = props.editor?.getModel()

                if (model) {
                    actions.createTab()
                }
            }
        },
        setQueryInput: () => {
            actions.updateState()
        },
        updateState: async (_, breakpoint) => {
            await breakpoint(100)
            const queries = values.allTabs.map((model) => {
                return {
                    query: props.monaco?.editor.getModel(model)?.getValue() || '',
                    path: model.path.split('/').pop(),
                }
            })
            localStorage.setItem(editorModelsStateKey(props.key), JSON.stringify(queries))
        },
        runQuery: ({ queryOverride }) => {
            actions.setActiveQuery(queryOverride || values.queryInput)
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
                onSubmit: ({ viewName }) => actions.saveAsViewSuccess(viewName),
            })
        },
        saveAsViewSuccess: async ({ name }) => {
            const query: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: values.queryInput,
            }
            await dataWarehouseViewsLogic.asyncActions.createDataWarehouseSavedQuery({ name, query })
        },
        reloadMetadata: async (_, breakpoint) => {
            const model = props.editor?.getModel()
            if (!model || !props.monaco) {
                return
            }
            await breakpoint(300)
            const query = values.queryInput
            if (query === '') {
                return
            }

            const response = await performQuery<HogQLMetadata>({
                kind: NodeKind.HogQLMetadata,
                language: HogLanguage.hogQL,
                query: query,
            })
            breakpoint()
            actions.setMetadata(query, response)
        },
    })),
    subscriptions(({ props, actions, values }) => ({
        activeModelUri: (activeModelUri) => {
            if (props.monaco) {
                const _model = props.monaco.editor.getModel(activeModelUri)
                const val = _model?.getValue()
                actions.setQueryInput(val ?? '')
                actions.runQuery()
                dataNodeLogic({
                    key: values.activeTabKey,
                    query: {
                        kind: NodeKind.HogQLQuery,
                        query: val ?? '',
                    },
                    doNotLoad: !val,
                }).mount()
            }
        },
        queryInput: () => {
            actions.reloadMetadata()
        },
    })),
    selectors({
        activeTabKey: [(s) => [s.activeModelUri], (activeModelUri) => `hogQLQueryEditor/${activeModelUri?.path}`],
        isValidView: [(s) => [s.metadata], (metadata) => !!(metadata && metadata[1]?.isValidView)],
        hasErrors: [
            (s) => [s.modelMarkers],
            (modelMarkers) => !!(modelMarkers ?? []).filter((e) => e.severity === 8 /* MarkerSeverity.Error */).length,
        ],
        error: [
            (s) => [s.hasErrors, s.modelMarkers],
            (hasErrors, modelMarkers) => {
                const firstError = modelMarkers.find((e) => e.severity === 8 /* MarkerSeverity.Error */)
                return hasErrors && firstError
                    ? `Error on line ${firstError.startLineNumber}, column ${firstError.startColumn}`
                    : null
            },
        ],
    }),
])
