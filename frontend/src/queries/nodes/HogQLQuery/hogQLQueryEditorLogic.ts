import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { HogQLMetadata, HogQLQuery, NodeKind } from '~/queries/schema'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'
import { editor, MarkerSeverity } from 'monaco-editor'
import { query } from '~/queries/query'
import { Monaco } from '@monaco-editor/react'

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface ModelMarker extends editor.IMarkerData {}

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
        if (props.query.query !== oldProps.query.query) {
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
        hasErrors: [(s) => [s.modelMarkers], (modelMarkers) => !!modelMarkers?.length],
        error: [
            (s) => [s.hasErrors, s.modelMarkers],
            (hasErrors, modelMarkers) =>
                hasErrors && modelMarkers[0]
                    ? `Error on line ${modelMarkers[0].startLineNumber}, column ${modelMarkers[0].startColumn}`
                    : null,
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
            if (!response?.isValid) {
                const start = model.getPositionAt(response?.errorStart ?? 0)
                const end = model.getPositionAt(response?.errorEnd ?? queryInput.length)
                const markers: ModelMarker[] = [
                    {
                        startLineNumber: start.lineNumber,
                        startColumn: start.column,
                        endLineNumber: end.lineNumber,
                        endColumn: end.column,
                        message: response?.error ?? 'Unknown error',
                        severity: MarkerSeverity.Error,
                    },
                ]
                actions.setModelMarkers(markers)
            } else {
                actions.setModelMarkers([])
            }
        },
        setModelMarkers: ({ markers }) => {
            const model = props.editor?.getModel()
            if (model) {
                props.monaco?.editor.setModelMarkers(model, 'hogql', markers)
            }
        },
    })),
])
