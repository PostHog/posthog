import type { Monaco } from '@monaco-editor/react'
import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
// Note: we can oly import types and not values from monaco-editor, because otherwise some Monaco code breaks
// auto reload in development. Specifically, on this line:
// `export const suggestWidgetStatusbarMenu = new MenuId('suggestWidgetStatusBar')`
// `new MenuId('suggestWidgetStatusBar')` causes the app to crash, because it cannot be called twice in the same
// JS context, and that's exactly what happens on auto-reload when the new script chunks are loaded. Unfortunately
// esbuild doesn't support manual chunks as of 2023, so we can't just put Monaco in its own chunk, which would prevent
// re-importing. As for @monaco-editor/react, it does some lazy loading and doesn't have this problem.
import { editor, MarkerSeverity, Uri } from 'monaco-editor'

import { examples } from '~/queries/examples'
import { performQuery } from '~/queries/query'
import {
    AnyDataNode,
    DataVisualizationNode,
    HogLanguage,
    HogQLFilters,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLNotice,
    NodeKind,
} from '~/queries/schema'

import type { codeEditorLogicType } from './codeEditorLogicType'

export const editorModelsStateKey = (key: string | number): string => `${key}/editorModelQueries`
export const activemodelStateKey = (key: string | number): string => `${key}/activeModelUri`

const METADATA_LANGUAGES = [HogLanguage.hog, HogLanguage.hogQL, HogLanguage.hogQLExpr, HogLanguage.hogTemplate]

export interface ModelMarker extends editor.IMarkerData {
    hogQLFix?: string
    start: number
    end: number
}

export interface CodeEditorLogicProps {
    key: string
    query: string
    language: string
    sourceQuery?: AnyDataNode
    metadataFilters?: HogQLFilters
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
    globals?: Record<string, any>
    multitab?: boolean
}

export const codeEditorLogic = kea<codeEditorLogicType>([
    path(['lib', 'monaco', 'hogQLMetadataProvider']),
    props({} as CodeEditorLogicProps),
    key((props) => props.key),
    actions({
        reloadMetadata: true,
        createModel: true,
        addModel: (modelName: Uri) => ({ modelName }),
        setModel: (modelName: Uri) => ({ modelName }),
        deleteModel: (modelName: Uri) => ({ modelName }),
        removeModel: (modelName: Uri) => ({ modelName }),
        setModels: (models: Uri[]) => ({ models }),
        updateState: true,
        setLocalState: (key: string, value: any) => ({ key, value }),
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    loaders(({ props }) => ({
        metadata: [
            null as null | [string, HogQLMetadataResponse],
            {
                reloadMetadata: async (_, breakpoint) => {
                    const model = props.editor?.getModel()
                    if (!model || !props.monaco || !METADATA_LANGUAGES.includes(props.language as HogLanguage)) {
                        return null
                    }
                    await breakpoint(300)
                    const query = props.query
                    if (query === '') {
                        return null
                    }

                    const variables =
                        props.sourceQuery?.kind === NodeKind.HogQLQuery
                            ? props.sourceQuery.variables ?? undefined
                            : undefined

                    const response = await performQuery<HogQLMetadata>({
                        kind: NodeKind.HogQLMetadata,
                        language: props.language as HogLanguage,
                        query: query,
                        filters: props.metadataFilters,
                        globals: props.globals,
                        sourceQuery: props.sourceQuery,
                        variables,
                    })
                    breakpoint()
                    return [query, response]
                },
            },
        ],
        modelMarkers: [
            [] as ModelMarker[],
            {
                reloadMetadataSuccess: ({ metadata }) => {
                    const model = props.editor?.getModel()
                    if (!model || !metadata) {
                        return []
                    }
                    const markers: ModelMarker[] = []
                    const [query, metadataResponse] = metadata

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
    reducers({
        activeModelUri: [
            null as null | Uri,
            {
                setModel: (_, { modelName }) => modelName,
            },
        ],
        allModels: [
            [] as Uri[],
            {
                addModel: (state, { modelName }) => {
                    const newModels = [...state, modelName]
                    return newModels
                },
                removeModel: (state, { modelName }) => {
                    const newModels = state.filter((model) => model.toString() !== modelName.toString())
                    return newModels
                },
                setModels: (_, { models }) => models,
            },
        ],
    }),
    listeners(({ props, values, actions }) => ({
        addModel: () => {
            if (values.featureFlags[FEATURE_FLAGS.MULTITAB_EDITOR]) {
                const queries = values.allModels.map((model) => {
                    return {
                        query:
                            props.monaco?.editor.getModel(model)?.getValue() ||
                            (examples.DataWarehouse as DataVisualizationNode).source.query,
                        path: model.path.split('/').pop(),
                    }
                })
                props.multitab && actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        removeModel: () => {
            if (values.featureFlags[FEATURE_FLAGS.MULTITAB_EDITOR]) {
                const queries = values.allModels.map((model) => {
                    return {
                        query:
                            props.monaco?.editor.getModel(model)?.getValue() ||
                            (examples.DataWarehouse as DataVisualizationNode).source.query,
                        path: model.path.split('/').pop(),
                    }
                })
                props.multitab && actions.setLocalState(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        setModel: ({ modelName }) => {
            if (props.monaco) {
                const model = props.monaco.editor.getModel(modelName)
                props.editor?.setModel(model)
            }

            if (values.featureFlags[FEATURE_FLAGS.MULTITAB_EDITOR]) {
                const path = modelName.path.split('/').pop()
                path && props.multitab && actions.setLocalState(activemodelStateKey(props.key), path)
            }
        },
        deleteModel: ({ modelName }) => {
            if (props.monaco) {
                const model = props.monaco.editor.getModel(modelName)
                if (modelName == values.activeModelUri) {
                    const indexOfModel = values.allModels.findIndex(
                        (model) => model.toString() === modelName.toString()
                    )
                    const nextModel =
                        values.allModels[indexOfModel + 1] || values.allModels[indexOfModel - 1] || values.allModels[0] // there will always be one
                    actions.setModel(nextModel)
                }
                model?.dispose()
                actions.removeModel(modelName)
            }
        },
        setLocalState: ({ key, value }) => {
            localStorage.setItem(key, value)
        },
        updateState: async (_, breakpoint) => {
            await breakpoint(100)
            if (values.featureFlags[FEATURE_FLAGS.MULTITAB_EDITOR]) {
                const queries = values.allModels.map((model) => {
                    return {
                        query:
                            props.monaco?.editor.getModel(model)?.getValue() ||
                            (examples.DataWarehouse as DataVisualizationNode).source.query,
                        path: model.path.split('/').pop(),
                    }
                })
                props.multitab && localStorage.setItem(editorModelsStateKey(props.key), JSON.stringify(queries))
            }
        },
        createModel: () => {
            let currentModelCount = 1
            const allNumbers = values.allModels.map((model) => parseInt(model.path.split('/').pop() || '0'))
            while (allNumbers.includes(currentModelCount)) {
                currentModelCount++
            }

            if (props.monaco) {
                const uri = props.monaco.Uri.parse(currentModelCount.toString())
                const model = props.monaco.editor.createModel('SELECT event FROM events LIMIT 100', props.language, uri)
                props.editor?.setModel(model)
                actions.setModel(uri)
                actions.addModel(uri)
            }
        },
    })),
    selectors({
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
    propsChanged(({ actions, props }, oldProps) => {
        if (
            props.query !== oldProps.query ||
            props.language !== oldProps.language ||
            props.editor !== oldProps.editor
        ) {
            actions.reloadMetadata()
        }
    }),
])
