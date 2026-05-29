import equal from 'fast-deep-equal'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { SQLEditor, SQLEditorPanel } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { DataVisualizationNode, NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { convertDataTableNodeToDataVisualizationNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { NotebookNodeAttributeProperties, NotebookNodeAttributes, NotebookNodeProps } from '../../types'

export const EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT = 500
export const EMBEDDED_SQL_EDITOR_MIN_HEIGHT = 200

export const getNotebookSqlEditorTabId = (nodeId: string | null | undefined, suffix: string | null = null): string =>
    `notebook-sql-${suffix ? `${suffix}-` : ''}${nodeId ?? 'new'}`

export const getSqlEditorSourceQuery = (query: QuerySchema): DataVisualizationNode | null => {
    const convertedQuery = convertDataTableNodeToDataVisualizationNode(query)

    if (isDataVisualizationNode(convertedQuery) && isHogQLQuery(convertedQuery.source)) {
        return convertedQuery
    }

    if (isHogQLQuery(query)) {
        return {
            kind: NodeKind.DataVisualizationNode,
            source: query,
            display: ChartDisplayType.ActionsTable,
        }
    }

    return null
}

const buildSourceQuery = (query: string): DataVisualizationNode => ({
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query,
    },
    display: ChartDisplayType.ActionsTable,
})

export function useNotebookQuerySQLEditorSync<T extends { query: QuerySchema }>({
    attributes,
    updateAttributes,
    tabId,
}: NotebookNodeAttributeProperties<T> & { tabId: string }): DataVisualizationNode | null {
    const editorSourceQuery = useMemo(() => getSqlEditorSourceQuery(attributes.query), [attributes.query])
    const logic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { queryInput, sourceQuery } = useValues(logic)
    const { initialize, runQuery, setQueryInput, setSourceQuery } = useActions(logic)

    // Sync Tiptap node attributes with sqlEditorLogic kea state. Two refs let us tell apart
    // a remote attribute update (pull into kea) from a local edit (push to Tiptap).
    const lastAttrRef = useRef<DataVisualizationNode | null>(null)
    const lastLocalRef = useRef<DataVisualizationNode | null>(null)

    useEffect(() => {
        initialize()
    }, [initialize])

    useEffect(() => {
        if (!editorSourceQuery) {
            return
        }

        const localQuery: DataVisualizationNode = {
            ...sourceQuery,
            source: {
                ...sourceQuery.source,
                query: queryInput ?? '',
            },
            display: sourceQuery.display ?? editorSourceQuery.display ?? ChartDisplayType.ActionsTable,
        }

        if (equal(localQuery, editorSourceQuery)) {
            lastAttrRef.current = editorSourceQuery
            lastLocalRef.current = localQuery
            return
        }

        if (!equal(editorSourceQuery, lastAttrRef.current)) {
            // Attribute moved — pull (overrides any in-flight typing: last write wins).
            // On first mount `lastAttrRef.current` is null, so we also seed kea here and
            // kick off an initial `runQuery` so results show on load. We deliberately don't
            // re-run on subsequent remote updates: that would fire a backend query every
            // time another tab edits a keystroke through the collab stream.
            const isFirstSeed = lastAttrRef.current === null
            lastAttrRef.current = editorSourceQuery
            lastLocalRef.current = editorSourceQuery
            setQueryInput(editorSourceQuery.source.query)
            setSourceQuery(editorSourceQuery)
            if (isFirstSeed) {
                runQuery(editorSourceQuery.source.query)
            }
            return
        }

        if (!equal(localQuery, lastLocalRef.current)) {
            // Editor moved — push to Tiptap.
            lastLocalRef.current = localQuery
            updateAttributes({ query: localQuery } as Partial<NotebookNodeAttributes<T>>)
            return
        }

        // Tiptap hasn't propagated a push we already made — wait for the next render.
    }, [editorSourceQuery, queryInput, sourceQuery, runQuery, setQueryInput, setSourceQuery, updateAttributes])

    return editorSourceQuery
}

export function useNotebookCodeSQLEditorSync<T extends { code: string }>({
    attributes,
    updateAttributes,
    tabId,
}: NotebookNodeAttributeProperties<T> & { tabId: string }): void {
    const code = typeof attributes.code === 'string' ? attributes.code : ''
    const logic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { queryInput } = useValues(logic)
    const { initialize, setQueryInput, setSourceQuery } = useActions(logic)

    // Tracks the last `code` and `queryInput` we observed in sync. A real attribute change
    // (remote step, undo, programmatic) shows up as `code !== lastCodeRef` → pull. A real
    // local edit shows up as `queryInput !== lastQueryRef` → push. A transient mismatch
    // right after a push (Tiptap hasn't propagated yet) shows up as neither → wait.
    // One ref isn't enough: after a push it would falsely classify the lag as a remote change.
    const lastCodeRef = useRef<string | null>(null)
    const lastQueryRef = useRef<string | null>(null)

    useEffect(() => {
        initialize()
    }, [initialize])

    useEffect(() => {
        if (queryInput === code) {
            lastCodeRef.current = code
            lastQueryRef.current = queryInput
            return
        }

        if (code !== lastCodeRef.current) {
            // Attribute moved — pull into kea (overrides any in-flight typing: last write wins).
            lastCodeRef.current = code
            lastQueryRef.current = code
            setQueryInput(code)
            setSourceQuery(buildSourceQuery(code))
            return
        }

        if (queryInput !== lastQueryRef.current) {
            // Editor moved — push to Tiptap and keep sourceQuery in step with the new SQL so
            // "Run query" uses what the user is actually looking at. Skip the push when
            // queryInput resets to null (e.g. a re-initialize while `code` hasn't changed) —
            // otherwise we'd write `code: null` and clear the cell on the next round-trip.
            lastQueryRef.current = queryInput
            if (queryInput !== null) {
                setSourceQuery(buildSourceQuery(queryInput))
                updateAttributes({ code: queryInput } as Partial<NotebookNodeAttributes<T>>)
            }
            return
        }

        // Both sides match what we last observed but each other doesn't — Tiptap is still
        // catching up to a push we already made. Do nothing; the next render will reconcile.
    }, [code, queryInput, setQueryInput, setSourceQuery, updateAttributes])
}

export function NotebookSQLEditorOutput<T extends { query: QuerySchema }>({
    attributes,
    updateAttributes,
    showOutputToolbar,
}: NotebookNodeProps<T> & { showOutputToolbar: boolean }): JSX.Element | null {
    const tabId = useMemo(() => getNotebookSqlEditorTabId(attributes.nodeId), [attributes.nodeId])
    const editorSourceQuery = useNotebookQuerySQLEditorSync({ attributes, updateAttributes, tabId })

    if (!editorSourceQuery) {
        return null
    }

    return (
        <div
            className="flex h-full min-h-0 flex-col"
            onMouseDown={(event) => event.stopPropagation()}
            onDragStart={(event) => event.stopPropagation()}
        >
            <SQLEditor
                tabId={tabId}
                mode={SQLEditorMode.Embedded}
                panel={SQLEditorPanel.Output}
                defaultShowDatabaseTree={false}
                showOutputToolbar={showOutputToolbar}
            />
        </div>
    )
}

export function NotebookSQLEditorSettings<T extends { query: QuerySchema }>({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<T>): JSX.Element {
    const tabId = useMemo(() => getNotebookSqlEditorTabId(attributes.nodeId), [attributes.nodeId])
    const editorSourceQuery = useNotebookQuerySQLEditorSync({ attributes, updateAttributes, tabId })

    if (!editorSourceQuery) {
        return <></>
    }

    const editorHeight = attributes.height ?? EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT

    return (
        <div
            className="h-full min-h-0 overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: editorHeight, minHeight: EMBEDDED_SQL_EDITOR_MIN_HEIGHT }}
            onMouseDown={(event) => event.stopPropagation()}
            onDragStart={(event) => event.stopPropagation()}
        >
            <SQLEditor
                tabId={tabId}
                mode={SQLEditorMode.Embedded}
                panel={SQLEditorPanel.Query}
                defaultShowDatabaseTree={false}
            />
        </div>
    )
}

export function NotebookCodeSQLEditorSettings<T extends { code: string }>({
    attributes,
    updateAttributes,
    tabIdSuffix,
    onRunQuery,
    runQueryLoading,
    runQueryDisabledReason,
    runQueryTooltip,
}: NotebookNodeAttributeProperties<T> & {
    tabIdSuffix: string
    onRunQuery?: () => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
}): JSX.Element {
    const tabId = useMemo(
        () => getNotebookSqlEditorTabId(attributes.nodeId, tabIdSuffix),
        [attributes.nodeId, tabIdSuffix]
    )
    useNotebookCodeSQLEditorSync({ attributes, updateAttributes, tabId })
    const editorHeight = attributes.height ?? EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT

    return (
        <div
            className="h-full min-h-0 overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: editorHeight, minHeight: EMBEDDED_SQL_EDITOR_MIN_HEIGHT }}
            onMouseDown={(event) => event.stopPropagation()}
            onDragStart={(event) => event.stopPropagation()}
        >
            <SQLEditor
                tabId={tabId}
                mode={SQLEditorMode.Embedded}
                panel={SQLEditorPanel.Query}
                defaultShowDatabaseTree={false}
                onRunQuery={onRunQuery}
                runQueryLoading={runQueryLoading}
                runQueryDisabledReason={runQueryDisabledReason}
                runQueryTooltip={runQueryTooltip}
            />
        </div>
    )
}
