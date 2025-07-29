import type { Monaco } from '@monaco-editor/react'
import { actions, connect, kea, key, path, props, propsChanged, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
// Note: we can oly import types and not values from monaco-editor, because otherwise some Monaco code breaks
// auto reload in development. Specifically, on this line:
// `export const suggestWidgetStatusbarMenu = new MenuId('suggestWidgetStatusBar')`
// `new MenuId('suggestWidgetStatusBar')` causes the app to crash, because it cannot be called twice in the same
// JS context, and that's exactly what happens on auto-reload when the new script chunks are loaded. Unfortunately
// esbuild doesn't support manual chunks as of 2023, so we can't just put Monaco in its own chunk, which would prevent
// re-importing. As for @monaco-editor/react, it does some lazy loading and doesn't have this problem.
import { editor, MarkerSeverity } from 'monaco-editor'

import { performQuery } from '~/queries/query'
import {
    AnyDataNode,
    HogLanguage,
    HogQLFilters,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLNotice,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import type { codeEditorLogicType } from './codeEditorLogicType'

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
    onError?: (error: string | null) => void
    onMetadata?: (metadata: HogQLMetadataResponse | null) => void
    onMetadataLoading?: (loading: boolean) => void
}

export const codeEditorLogic = kea<codeEditorLogicType>([
    path(['lib', 'monaco', 'hogQLMetadataProvider']),
    props({} as CodeEditorLogicProps),
    key((props) => props.key),
    actions({
        reloadMetadata: true,
    }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    loaders(({ props }) => ({
        metadata: [
            null as null | [string, HogQLMetadataResponse],
            {
                reloadMetadata: async (_, breakpoint) => {
                    const model = props.editor?.getModel()
                    if (!model || !props.monaco || !METADATA_LANGUAGES.includes(props.language as HogLanguage)) {
                        props.onMetadata?.(null)
                        return null
                    }
                    await breakpoint(300)
                    const query = props.query
                    if (query === '') {
                        props.onMetadata?.(null)
                        return null
                    }

                    const variables =
                        props.sourceQuery?.kind === NodeKind.HogQLQuery
                            ? props.sourceQuery.variables ?? undefined
                            : undefined

                    const response = await performQuery<HogQLMetadata>(
                        setLatestVersionsOnQuery(
                            {
                                kind: NodeKind.HogQLMetadata,
                                language: props.language as HogLanguage,
                                query: query,
                                filters: props.metadataFilters,
                                globals: props.globals,
                                sourceQuery: props.sourceQuery,
                                variables,
                            },
                            { recursion: false }
                        )
                    )
                    breakpoint()
                    props.onMetadata?.(response)
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
    }),
    subscriptions(({ props }) => ({
        error: (error) => {
            props.onError?.(error)
        },
        metadataLoading: (loading) => {
            props.onMetadataLoading?.(loading)
        },
    })),
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
