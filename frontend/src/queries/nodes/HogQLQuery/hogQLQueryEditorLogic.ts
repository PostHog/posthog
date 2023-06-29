import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { HogQLMetadata, HogQLNotice, HogQLQuery, NodeKind } from '~/queries/schema'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'
import { editor, MarkerSeverity } from 'monaco-editor'
import { query } from '~/queries/query'
import { Monaco } from '@monaco-editor/react'

export interface ModelMarker extends editor.IMarkerData {
    hogQLFix?: string
}

export interface HogQLQueryEditorLogicProps {
    key: number
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

export const hogQLQueryEditorLogic = kea<hogQLQueryEditorLogicType>([
    path(['queries', 'nodes', 'HogQLQuery', 'hogQLQueryEditorLogic']),
    props({} as HogQLQueryEditorLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.query.query !== oldProps.query.query || props.editor !== oldProps.editor) {
            actions.setQueryInput(props.query.query)
        }
    }),
    actions({
        saveQuery: true,
        setQueryInput: (queryInput: string) => ({ queryInput }),
        setModelMarkers: (markers: ModelMarker[]) => ({ markers }),
    }),
    reducers(({ props }) => ({
        queryInput: [props.query.query, { setQueryInput: (_, { queryInput }) => queryInput }],
        modelMarkers: [[] as ModelMarker[], { setModelMarkers: (_, { markers }) => markers }],
    })),
    selectors({
        hasErrors: [
            (s) => [s.modelMarkers],
            (modelMarkers) => !!(modelMarkers ?? []).filter((e) => e.severity === MarkerSeverity.Error).length,
        ],
        error: [
            (s) => [s.hasErrors, s.modelMarkers],
            (hasErrors, modelMarkers) => {
                const firstError = modelMarkers.find((e) => e.severity === MarkerSeverity.Error)
                return hasErrors && firstError
                    ? `Error on line ${firstError.startLineNumber}, column ${firstError.startColumn}`
                    : null
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        saveQuery: () => {
            const query = values.queryInput
            actions.setQueryInput(query)
            props.setQuery?.({ ...props.query, query })
        },
        setQueryInput: async (_, breakpoint) => {
            if (!props.editor || !props.monaco) {
                return
            }
            const model = props.editor?.getModel()
            if (!model) {
                return
            }
            await breakpoint(300)
            const { queryInput } = values
            const response = await query<HogQLMetadata>({
                kind: NodeKind.HogQLMetadata,
                select: queryInput,
            })
            breakpoint()
            const markers: ModelMarker[] = []

            function noticeToMarker(error: HogQLNotice, severity: MarkerSeverity): void {
                if (!model) {
                    return
                }
                const start = model.getPositionAt(error.start ?? 0)
                const end = model.getPositionAt(error.end ?? queryInput.length)
                markers.push({
                    startLineNumber: start.lineNumber,
                    startColumn: start.column,
                    endLineNumber: end.lineNumber,
                    endColumn: end.column,
                    message: error.message ?? 'Unknown error',
                    severity: severity,
                    hogQLFix: error.fix,
                })
            }
            for (const notice of response?.errors ?? []) {
                noticeToMarker(notice, MarkerSeverity.Error)
            }
            for (const notice of response?.warnings ?? []) {
                noticeToMarker(notice, MarkerSeverity.Warning)
            }
            for (const notice of response?.notices ?? []) {
                noticeToMarker(notice, MarkerSeverity.Hint)
            }

            actions.setModelMarkers(markers)
        },
        setModelMarkers: ({ markers }) => {
            const model = props.editor?.getModel()
            if (model) {
                props.monaco?.editor.setModelMarkers(model, 'hogql', markers)
            }
        },
    })),
])
