import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { HogQLMetadata, HogQLQuery, NodeKind } from '~/queries/schema'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'
import { editor as importedEditor, MarkerSeverity } from 'monaco-editor'
import { query } from '~/queries/query'
import { Monaco } from '@monaco-editor/react'

export interface HogQLQueryEditorLogicProps {
    key: number
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
    monaco?: Monaco | null
    editor?: importedEditor.IStandaloneCodeEditor | null
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
    }),
    reducers(({ props }) => ({
        queryInput: [props.query.query, { setQueryInput: (_, { queryInput }) => queryInput }],
    })),
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
                const markers: importedEditor.IMarkerData[] = [
                    {
                        startLineNumber: start.lineNumber,
                        startColumn: start.column,
                        endLineNumber: end.lineNumber,
                        endColumn: end.column,
                        message: response?.error ?? 'Unknown error',
                        severity: MarkerSeverity.Error,
                    },
                ]
                props.monaco.editor.setModelMarkers(model, 'hogql', markers)
            } else {
                props.monaco.editor.setModelMarkers(model, 'hogql', [])
            }
        },
    })),
])
