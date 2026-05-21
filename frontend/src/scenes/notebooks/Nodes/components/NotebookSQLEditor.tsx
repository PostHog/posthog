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
    const lastAttributeQuery = useRef<DataVisualizationNode | null>(null)
    const suppressNextWriteback = useRef(false)

    useEffect(() => {
        initialize()
    }, [initialize])

    useEffect(() => {
        if (!editorSourceQuery) {
            lastAttributeQuery.current = null
            return
        }

        if (lastAttributeQuery.current && equal(lastAttributeQuery.current, editorSourceQuery)) {
            return
        }

        lastAttributeQuery.current = editorSourceQuery
        suppressNextWriteback.current = true

        if (queryInput !== editorSourceQuery.source.query) {
            setQueryInput(editorSourceQuery.source.query)

            if (queryInput === null) {
                runQuery(editorSourceQuery.source.query)
            }
        }

        if (!equal(sourceQuery, editorSourceQuery)) {
            setSourceQuery(editorSourceQuery)
        }
    }, [editorSourceQuery, queryInput, runQuery, setQueryInput, setSourceQuery, sourceQuery])

    useEffect(() => {
        if (suppressNextWriteback.current) {
            suppressNextWriteback.current = false
            return
        }

        if (!editorSourceQuery || queryInput === null) {
            return
        }

        const nextQuery: DataVisualizationNode = {
            ...sourceQuery,
            source: {
                ...sourceQuery.source,
                query: queryInput,
            },
            display: sourceQuery.display ?? editorSourceQuery.display ?? ChartDisplayType.ActionsTable,
        }

        if (!equal(nextQuery, editorSourceQuery)) {
            updateAttributes({ query: nextQuery } as Partial<NotebookNodeAttributes<T>>)
        }
    }, [editorSourceQuery, queryInput, sourceQuery, updateAttributes])

    return editorSourceQuery
}

export function useNotebookCodeSQLEditorSync<T extends { code: string }>({
    attributes,
    updateAttributes,
    tabId,
}: NotebookNodeAttributeProperties<T> & { tabId: string }): void {
    const code = typeof attributes.code === 'string' ? attributes.code : ''
    const logic = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
    const { queryInput, sourceQuery } = useValues(logic)
    const { initialize, setQueryInput, setSourceQuery } = useActions(logic)
    const lastAttributeCode = useRef<string | null>(null)
    const suppressNextWriteback = useRef(false)

    useEffect(() => {
        initialize()
    }, [initialize])

    useEffect(() => {
        if (lastAttributeCode.current === code) {
            return
        }

        lastAttributeCode.current = code
        suppressNextWriteback.current = true

        if (queryInput !== code) {
            setQueryInput(code)
        }

        const nextSourceQuery = buildSourceQuery(code)
        if (!equal(nextSourceQuery, sourceQuery)) {
            setSourceQuery(nextSourceQuery)
        }
    }, [code, queryInput, setQueryInput, setSourceQuery, sourceQuery])

    useEffect(() => {
        if (suppressNextWriteback.current) {
            suppressNextWriteback.current = false
            return
        }

        if (queryInput === null || queryInput === code) {
            return
        }

        updateAttributes({ code: queryInput } as Partial<NotebookNodeAttributes<T>>)

        const nextSourceQuery = {
            ...sourceQuery,
            source: {
                ...sourceQuery.source,
                query: queryInput,
            },
            display: sourceQuery.display ?? ChartDisplayType.ActionsTable,
        }

        if (!equal(nextSourceQuery, sourceQuery)) {
            setSourceQuery(nextSourceQuery)
        }
    }, [code, queryInput, setSourceQuery, sourceQuery, updateAttributes])
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
