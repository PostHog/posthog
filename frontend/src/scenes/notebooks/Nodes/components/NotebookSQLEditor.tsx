import equal from 'fast-deep-equal'
import { useActions, useValues } from 'kea'
import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { OutputTab, outputPaneLogic } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { SQLEditor, SQLEditorPanel } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { DataVisualizationNode, HogQLQuery, NodeKind, ProductKey, QuerySchema } from '~/queries/schema/schema-general'
import { convertDataTableNodeToDataVisualizationNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { NotebookNodeAttributeProperties, NotebookNodeAttributes, NotebookNodeProps } from '../../types'

export const EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT = 333
export const EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT = 150
export const EMBEDDED_SQL_EDITOR_MIN_HEIGHT = 200
export const EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT = 150

export const getNotebookSqlEditorTabId = (nodeId: string | null | undefined, suffix: string | null = null): string =>
    `notebook-sql-${suffix ? `${suffix}-` : ''}${nodeId ?? 'new'}`

const withNotebookHogQLTags = (query: DataVisualizationNode): DataVisualizationNode => ({
    ...query,
    source: {
        ...query.source,
        tags: {
            ...query.source.tags,
            productKey: query.source.tags?.productKey ?? ProductKey.NOTEBOOKS,
            scene: query.source.tags?.scene ?? 'Notebook',
        },
    },
})

export const getSqlEditorSourceQuery = (query: QuerySchema): DataVisualizationNode | null => {
    const convertedQuery = convertDataTableNodeToDataVisualizationNode(query)

    if (isDataVisualizationNode(convertedQuery) && isHogQLQuery(convertedQuery.source)) {
        return withNotebookHogQLTags(convertedQuery)
    }

    if (isHogQLQuery(query)) {
        return withNotebookHogQLTags({
            kind: NodeKind.DataVisualizationNode,
            source: query,
            display: ChartDisplayType.ActionsTable,
        })
    }

    return null
}

const buildSourceQuery = (query: string): DataVisualizationNode => ({
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query,
        tags: {
            productKey: ProductKey.NOTEBOOKS,
            scene: 'Notebook',
        },
    },
    display: ChartDisplayType.ActionsTable,
})

const locallyPushedSqlEditorSourceQueryByTabId = new Map<string, DataVisualizationNode>()

export function getEmbeddedSqlEditorStyle(
    height: string | number | undefined,
    defaultHeight: string | number = EMBEDDED_SQL_EDITOR_DEFAULT_HEIGHT,
    minHeight: string | number = EMBEDDED_SQL_EDITOR_MIN_HEIGHT
): CSSProperties {
    return {
        height: height ?? defaultHeight,
        minHeight,
    }
}

function getRunnableHogQLSource(source: HogQLQuery): Omit<HogQLQuery, 'tags'> {
    const { tags: _tags, ...runnableSource } = {
        ...source,
        sendRawQuery: source.connectionId ? source.sendRawQuery || undefined : undefined,
    }
    return runnableSource
}

export function hasAlreadyRunSqlEditorSourceQuery(
    editorSourceQuery: DataVisualizationNode,
    lastRunQuery: DataVisualizationNode | null
): boolean {
    return (
        !!lastRunQuery &&
        equal(getRunnableHogQLSource(editorSourceQuery.source), getRunnableHogQLSource(lastRunQuery.source))
    )
}

export function useNotebookQuerySQLEditorSync<T extends { query: QuerySchema }>({
    attributes,
    updateAttributes,
    tabId,
    autoRunOnFirstSeed = true,
}: NotebookNodeAttributeProperties<T> & { tabId: string; autoRunOnFirstSeed?: boolean }): DataVisualizationNode | null {
    const editorSourceQuery = useMemo(() => getSqlEditorSourceQuery(attributes.query), [attributes.query])
    const logic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { queryInput, sourceQuery, lastRunQuery } = useValues(logic)
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
            // On first mount `lastAttrRef.current` is null, so seed kea and auto-run if
            // this tab has not already run the same data-bearing SQL source. The output
            // and edit panels mount separate sync hooks for the same tab, so the edit panel
            // must not reload data just because it mounted with fresh refs.
            const isFirstSeed = lastAttrRef.current === null
            lastAttrRef.current = editorSourceQuery
            lastLocalRef.current = editorSourceQuery
            setQueryInput(editorSourceQuery.source.query)
            setSourceQuery(editorSourceQuery)
            if (
                autoRunOnFirstSeed &&
                isFirstSeed &&
                !hasAlreadyRunSqlEditorSourceQuery(editorSourceQuery, lastRunQuery)
            ) {
                runQuery(editorSourceQuery.source.query)
            }
            return
        }

        if (!equal(localQuery, lastLocalRef.current)) {
            // Editor moved — push to Tiptap.
            lastLocalRef.current = localQuery
            locallyPushedSqlEditorSourceQueryByTabId.set(tabId, localQuery)
            updateAttributes({ query: localQuery } as Partial<NotebookNodeAttributes<T>>)
            return
        }

        // Tiptap hasn't propagated a push we already made — wait for the next render.
    }, [
        editorSourceQuery,
        autoRunOnFirstSeed,
        lastRunQuery,
        queryInput,
        sourceQuery,
        runQuery,
        setQueryInput,
        setSourceQuery,
        tabId,
        updateAttributes,
    ])

    return editorSourceQuery
}

function useNotebookQuerySQLEditorOutputSync<T extends { query: QuerySchema }>({
    attributes,
    tabId,
}: Pick<NotebookNodeAttributeProperties<T>, 'attributes'> & { tabId: string }): DataVisualizationNode | null {
    const editorSourceQuery = useMemo(() => getSqlEditorSourceQuery(attributes.query), [attributes.query])
    const logic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { lastRunQuery } = useValues(logic)
    const { initialize, runQuery, setQueryInput, setSourceQuery } = useActions(logic)
    const lastAttrRef = useRef<DataVisualizationNode | null>(null)

    useEffect(() => {
        initialize()
    }, [initialize])

    useEffect(() => {
        if (!editorSourceQuery || equal(editorSourceQuery, lastAttrRef.current)) {
            return
        }

        const isFirstSeed = lastAttrRef.current === null
        lastAttrRef.current = editorSourceQuery
        if (!isFirstSeed && equal(editorSourceQuery, locallyPushedSqlEditorSourceQueryByTabId.get(tabId))) {
            return
        }

        setQueryInput(editorSourceQuery.source.query)
        setSourceQuery(editorSourceQuery)
        if (isFirstSeed && !hasAlreadyRunSqlEditorSourceQuery(editorSourceQuery, lastRunQuery)) {
            runQuery(editorSourceQuery.source.query)
        }
    }, [editorSourceQuery, lastRunQuery, runQuery, setQueryInput, setSourceQuery, tabId])

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

export const getNotebookSqlEditorOutputTab = (outputTab: unknown): OutputTab => {
    if (Object.values(OutputTab).includes(outputTab as OutputTab)) {
        return outputTab as OutputTab
    }

    return OutputTab.Results
}

export function useNotebookSQLOutputTabSync<T extends { outputTab?: OutputTab | null }>({
    attributes,
    updateAttributes,
    tabId,
}: NotebookNodeAttributeProperties<T> & { tabId: string }): void {
    const attributeOutputTab = getNotebookSqlEditorOutputTab(attributes.outputTab)
    const logic = outputPaneLogic({ tabId })
    const { activeTab } = useValues(logic)
    const { setActiveTab } = useActions(logic)

    const lastAttrRef = useRef<OutputTab | null>(null)
    const lastLocalRef = useRef<OutputTab | null>(null)

    useEffect(() => {
        if (activeTab === attributeOutputTab) {
            lastAttrRef.current = attributeOutputTab
            lastLocalRef.current = activeTab
            return
        }

        if (attributeOutputTab !== lastAttrRef.current) {
            lastAttrRef.current = attributeOutputTab
            lastLocalRef.current = attributeOutputTab
            setActiveTab(attributeOutputTab)
            return
        }

        if (activeTab !== lastLocalRef.current) {
            lastLocalRef.current = activeTab
            updateAttributes({ outputTab: activeTab } as Partial<NotebookNodeAttributes<T>>)
        }
    }, [activeTab, attributeOutputTab, setActiveTab, updateAttributes])
}

export function NotebookSQLEditorOutput<T extends { query: QuerySchema; outputTab?: OutputTab | null }>({
    attributes,
    updateAttributes,
    showOutputToolbar,
}: NotebookNodeProps<T> & { showOutputToolbar: boolean }): JSX.Element | null {
    const tabId = useMemo(() => getNotebookSqlEditorTabId(attributes.nodeId), [attributes.nodeId])
    const editorSourceQuery = useNotebookQuerySQLEditorOutputSync({ attributes, tabId })
    useNotebookSQLOutputTabSync({ attributes, updateAttributes, tabId })

    if (!editorSourceQuery) {
        return null
    }

    return (
        <div
            className="flex min-h-0 flex-col overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={getEmbeddedSqlEditorStyle(attributes.height)}
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
    const editorSourceQuery = useNotebookQuerySQLEditorSync({
        attributes,
        updateAttributes,
        tabId,
        autoRunOnFirstSeed: false,
    })
    // Focus the editor only when this user just inserted the node - a node mounting on
    // notebook load or after a structural re-render must never steal the caret.
    const [autoFocusQueryPane] = useState(() => wasNotebookNodeJustInserted(attributes.nodeId))

    if (!editorSourceQuery) {
        return <></>
    }

    return (
        <div
            className="h-full min-h-0 overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={getEmbeddedSqlEditorStyle(
                attributes.height,
                EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT,
                EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT
            )}
            onMouseDown={(event) => event.stopPropagation()}
            onDragStart={(event) => event.stopPropagation()}
        >
            <SQLEditor
                tabId={tabId}
                mode={SQLEditorMode.Embedded}
                panel={SQLEditorPanel.Query}
                defaultShowDatabaseTree={false}
                queryPaneDefaultHeight={EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT}
                autoFocusQueryPane={autoFocusQueryPane}
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
    onCancelQuery,
    cancelQueryLoading,
}: NotebookNodeAttributeProperties<T> & {
    tabIdSuffix: string
    /** Called with the live editor text — `attributes.code` can lag it by a Tiptap round-trip. */
    onRunQuery?: (code: string) => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
    /** With onRunQuery: flips the run button to Cancel while runQueryLoading. */
    onCancelQuery?: () => void
    cancelQueryLoading?: boolean
}): JSX.Element {
    const tabId = useMemo(
        () => getNotebookSqlEditorTabId(attributes.nodeId, tabIdSuffix),
        [attributes.nodeId, tabIdSuffix]
    )
    useNotebookCodeSQLEditorSync({ attributes, updateAttributes, tabId })
    const editorLogic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { queryInput } = useValues(editorLogic)
    // Prefer what the user sees in the editor; fall back to the attribute before the first sync.
    const liveCode = queryInput ?? (typeof attributes.code === 'string' ? attributes.code : '')
    // Focus the editor only when this user just inserted the node - a node mounting on
    // notebook load or after a structural re-render must never steal the caret.
    const [autoFocusQueryPane] = useState(() => wasNotebookNodeJustInserted(attributes.nodeId))

    return (
        <div
            className="h-full min-h-0 overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={getEmbeddedSqlEditorStyle(
                attributes.height,
                EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT,
                EMBEDDED_SQL_EDITOR_EDIT_MIN_HEIGHT
            )}
            onMouseDown={(event) => event.stopPropagation()}
            onDragStart={(event) => event.stopPropagation()}
        >
            <SQLEditor
                tabId={tabId}
                mode={SQLEditorMode.Embedded}
                panel={SQLEditorPanel.Query}
                defaultShowDatabaseTree={false}
                autoFocusQueryPane={autoFocusQueryPane}
                // Read the editor's current text imperatively at run time. The Cmd+Enter keybinding
                // fires a stale closure (and Monaco's keybinding value can come through empty), so a
                // captured `liveCode` would run the previous query. The mounted logic's `queryInput`
                // is the same source the Run button uses; fall back to `liveCode` before first sync.
                onRunQuery={
                    onRunQuery
                        ? () => {
                              const current = editorLogic.values.queryInput
                              onRunQuery(typeof current === 'string' && current.trim() ? current : liveCode)
                          }
                        : undefined
                }
                runQueryLoading={runQueryLoading}
                runQueryDisabledReason={runQueryDisabledReason}
                runQueryTooltip={runQueryTooltip}
                onCancelQuery={onCancelQuery}
                cancelQueryLoading={cancelQueryLoading}
                queryPaneDefaultHeight={EMBEDDED_SQL_EDITOR_EDIT_DEFAULT_HEIGHT}
            />
        </div>
    )
}
