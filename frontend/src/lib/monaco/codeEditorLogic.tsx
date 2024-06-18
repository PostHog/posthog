import type { Monaco } from '@monaco-editor/react'
import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
// Note: we can oly import types and not values from monaco-editor, because otherwise some Monaco code breaks
// auto reload in development. Specifically, on this line:
// `export const suggestWidgetStatusbarMenu = new MenuId('suggestWidgetStatusBar')`
// `new MenuId('suggestWidgetStatusBar')` causes the app to crash, because it cannot be called twice in the same
// JS context, and that's exactly what happens on auto-reload when the new script chunks are loaded. Unfortunately
// esbuild doesn't support manual chunks as of 2023, so we can't just put Monaco in its own chunk, which would prevent
// re-importing. As for @monaco-editor/react, it does some lazy loading and doesn't have this problem.
import { editor, MarkerSeverity } from 'monaco-editor'

import { performQuery } from '~/queries/query'
import { HogQLFilters, HogQLMetadata, HogQLMetadataResponse, HogQLNotice, NodeKind } from '~/queries/schema'

import type { codeEditorLogicType } from './codeEditorLogicType'

export interface ModelMarker extends editor.IMarkerData {
    hogQLFix?: string
    start: number
    end: number
}

export interface CodeEditorLogicProps {
    key: string
    query: string
    language?: string
    metadataFilters?: HogQLFilters
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

export const codeEditorLogic = kea<codeEditorLogicType>([
    path(['lib', 'monaco', 'hogQLMetadataProvider']),
    props({} as CodeEditorLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.query !== oldProps.query || props.editor !== oldProps.editor) {
            actions.setQuery(props.query)
        }
    }),
    actions({
        setQuery: (query: string) => ({ query }),
    }),
    reducers(({ props }) => ({
        query: [props.query, { setQuery: (_, { query }) => query }],
    })),
    loaders(({ props, values }) => ({
        metadata: [
            null as null | [string, HogQLMetadataResponse],
            {
                setQuery: async (_, breakpoint) => {
                    if (!props.editor || !props.monaco) {
                        return null
                    }
                    const model = props.editor?.getModel()
                    if (!model) {
                        return null
                    }
                    await breakpoint(300)
                    const { query } = values
                    const response = await performQuery<HogQLMetadata>({
                        kind: NodeKind.HogQLMetadata,
                        select: query,
                        filters: props.metadataFilters,
                    })
                    breakpoint()
                    return [query, response]
                },
            },
        ],
        modelMarkers: [
            [] as ModelMarker[],
            {
                setQuerySuccess: ({ metadata }) => {
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
])
