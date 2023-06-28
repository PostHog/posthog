import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { HogQLMetadata, HogQLQuery, NodeKind } from '~/queries/schema'

import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'
import { editor, MarkerSeverity } from 'monaco-editor'
import { query } from '~/queries/query'
import { Monaco } from '@monaco-editor/react'
import api from 'lib/api'

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
        setPrompt: (prompt: string) => ({ prompt }),
        setPromptError: (error: string | null) => ({ error }),
        draftFromPrompt: true,
        draftFromPromptComplete: true,
    }),
    reducers(({ props }) => ({
        queryInput: [props.query.query, { setQueryInput: (_, { queryInput }) => queryInput }],
        modelMarkers: [[] as ModelMarker[], { setModelMarkers: (_, { markers }) => markers }],
        prompt: ['', { setPrompt: (_, { prompt }) => prompt }],
        promptError: [
            null as string | null,
            { setPromptError: (_, { error }) => error, draftFromPrompt: () => null, saveQuery: () => null },
        ],
        promptLoading: [false, { draftFromPrompt: () => true, draftFromPromptComplete: () => false }],
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
            // TODO: Is below line necessary if the only way for queryInput to change is already through setQueryInput?
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
        draftFromPrompt: async () => {
            try {
                const result = await api.get(`api/projects/@current/query/draft_sql/?prompt=${values.prompt}`)
                const { sql } = result
                actions.setQueryInput(sql)
            } catch (e) {
                actions.setPromptError(e.detail)
            } finally {
                actions.draftFromPromptComplete()
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
