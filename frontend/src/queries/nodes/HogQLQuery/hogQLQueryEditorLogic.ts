import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { HogQLMetadata, HogQLNotice, HogQLQuery, NodeKind } from '~/queries/schema'
import type { hogQLQueryEditorLogicType } from './hogQLQueryEditorLogicType'
// Note: we can oly import types and not values from monaco-editor, because otherwise some Monaco code breaks
// auto reload in development. Specifically, on this line:
// `export const suggestWidgetStatusbarMenu = new MenuId('suggestWidgetStatusBar')`
// `new MenuId('suggestWidgetStatusBar')` causes the app to crash, because it cannot be called twice in the same
// JS context, and that's exactly what happens on auto-reload when the new script chunks are loaded. Unfortunately
// esbuild doesn't support manual chunks as of 2023, so we can't just put Monaco in its own chunk, which would prevent
// re-importing. As for @monaco-editor/react, it does some lazy loading and doesn't have this problem.
import type { editor, MarkerSeverity } from 'monaco-editor'
import { query } from '~/queries/query'
import type { Monaco } from '@monaco-editor/react'
import api from 'lib/api'
import { combineUrl } from 'kea-router'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { dataWarehouseSavedQueriesLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseSavedQueriesLogic'
import { promptLogic } from 'lib/logic/promptLogic'

export interface ModelMarker extends editor.IMarkerData {
    hogQLFix?: string
    start: number
    end: number
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
    connect({
        actions: [dataWarehouseSavedQueriesLogic, ['createDataWarehouseSavedQuery']],
        logic: [promptLogic({ key: `save-as-view` })],
    }),
    actions({
        saveQuery: true,
        setQueryInput: (queryInput: string) => ({ queryInput }),
        setModelMarkers: (markers: ModelMarker[]) => ({ markers }),
        setPrompt: (prompt: string) => ({ prompt }),
        setPromptError: (error: string | null) => ({ error }),
        draftFromPrompt: true,
        draftFromPromptComplete: true,
        saveAsView: true,
        saveAsViewSuccess: (name: string) => ({ name }),
        setIsValidView: (isValid: boolean) => ({ isValid }),
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
        isValidView: [false, { setIsValidView: (_, { isValid }) => isValid }],
    })),
    selectors({
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
        aiAvailable: [() => [preflightLogic.selectors.preflight], (preflight) => preflight?.openai_available],
    }),
    listeners(({ actions, asyncActions, props, values }) => ({
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
                filters: props.query.filters,
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
                    start: error.start ?? 0,
                    startLineNumber: start.lineNumber,
                    startColumn: start.column,
                    end: error.end ?? queryInput.length,
                    endLineNumber: end.lineNumber,
                    endColumn: end.column,
                    message: error.message ?? 'Unknown error',
                    severity: severity,
                    hogQLFix: error.fix,
                })
            }
            for (const notice of response?.errors ?? []) {
                noticeToMarker(notice, 8 /* MarkerSeverity.Error */)
            }
            for (const notice of response?.warnings ?? []) {
                noticeToMarker(notice, 4 /* MarkerSeverity.Warning */)
            }
            for (const notice of response?.notices ?? []) {
                noticeToMarker(notice, 1 /* MarkerSeverity.Hint */)
            }
            actions.setIsValidView(response?.isValidView || false)
            actions.setModelMarkers(markers)
        },
        draftFromPrompt: async () => {
            if (!values.aiAvailable) {
                throw new Error(
                    'To use AI features, configure environment variable OPENAI_API_KEY for this instance of PostHog'
                )
            }
            try {
                const result = await api.get(
                    combineUrl(`api/projects/@current/query/draft_sql/`, {
                        prompt: values.prompt,
                        current_query: values.queryInput,
                    }).url
                )
                const { sql } = result
                actions.setQueryInput(sql)
            } catch (e) {
                actions.setPromptError((e as { code: string; detail: string }).detail)
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
        saveAsView: async () => {
            promptLogic({ key: `save-as-view` }).actions.prompt({
                title: 'Save as view',
                placeholder: 'Please enter the name of the view',
                value: '',
                error: 'You must enter a name',
                success: actions.saveAsViewSuccess,
            })
        },
        saveAsViewSuccess: async ({ name }) => {
            const query: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: values.queryInput,
            }
            await asyncActions.createDataWarehouseSavedQuery({ name, query })
        },
    })),
])
