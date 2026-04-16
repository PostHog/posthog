import './RawSqlDebug.scss'

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { rawSqlLogic } from './rawSqlLogic'
import type { QueryLogEntry, RawSqlColumn } from './rawSqlLogic'

export function RawSqlDebug(): JSX.Element {
    const { query, rawSqlResult, rawSqlResultLoading, rawSqlError, queryLogEntry, queryLogEntryLoading } =
        useValues(rawSqlLogic)
    const { setQuery, runQuery, cancelQuery } = useActions(rawSqlLogic)
    const [tab, setTab] = useState<string>('results')
    const [editorCollapsed, setEditorCollapsed] = useState(false)

    return (
        <div className="flex flex-col h-[70vh]">
            {/* Editor pane */}
            <div className="flex-shrink-0">
                <div className="flex items-center justify-between mb-1">
                    <div className="flex gap-2 items-center">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => runQuery()}
                            loading={rawSqlResultLoading}
                            disabledReason={rawSqlResultLoading ? 'Running...' : !query.trim() ? 'Enter a query' : null}
                        >
                            Run
                        </LemonButton>
                        {rawSqlResultLoading && (
                            <LemonButton size="small" type="secondary" status="danger" onClick={() => cancelQuery()}>
                                Cancel
                            </LemonButton>
                        )}
                        {rawSqlResult && (
                            <span className="text-xs text-muted">
                                {rawSqlResult.execution_time_ms}ms · {rawSqlResult.rows.length} rows
                                {rawSqlResult.truncated ? ' (truncated)' : ''}
                            </span>
                        )}
                    </div>
                    <LemonButton
                        size="small"
                        icon={editorCollapsed ? <IconExpand /> : <IconCollapse />}
                        onClick={() => setEditorCollapsed(!editorCollapsed)}
                    />
                </div>
                {!editorCollapsed && (
                    <CodeEditorResizeable
                        language="sql"
                        value={query}
                        onChange={(v) => setQuery(v ?? '')}
                        height={150}
                        minHeight="3rem"
                        maxHeight="40vh"
                        onPressCmdEnter={() => runQuery()}
                    />
                )}
            </div>

            {/* Results pane — fills remaining space */}
            <div className="flex-1 min-h-0 mt-2 flex flex-col">
                {rawSqlError && (
                    <LemonBanner type="error" className="text-xs font-mono">
                        {rawSqlError}
                    </LemonBanner>
                )}

                {rawSqlResult ? (
                    <>
                        {/* Tab bar stays fixed */}
                        <LemonTabs
                            activeKey={tab}
                            onChange={setTab}
                            tabs={[
                                { key: 'results', label: 'Results' },
                                {
                                    key: 'query_log',
                                    label: (
                                        <>
                                            Query log
                                            {queryLogEntryLoading && (
                                                <LemonTag size="small" className="ml-1">
                                                    Loading...
                                                </LemonTag>
                                            )}
                                        </>
                                    ),
                                },
                            ]}
                        />
                        {/* Tab content scrolls */}
                        <div className="flex-1 min-h-0 overflow-auto border rounded">
                            {tab === 'results' ? (
                                <ResultsTable columns={rawSqlResult.columns} rows={rawSqlResult.rows} />
                            ) : (
                                <QueryLogPanel entry={queryLogEntry} loading={queryLogEntryLoading} />
                            )}
                        </div>
                    </>
                ) : !rawSqlResultLoading ? (
                    <div className="text-muted text-sm p-4">Press Cmd+Enter or click Run to execute.</div>
                ) : null}
            </div>
        </div>
    )
}

const PAGE_SIZE = 50

function ResultsTable({ columns, rows }: { columns: RawSqlColumn[]; rows: any[][] }): JSX.Element {
    const [page, setPage] = useState(0)
    const totalPages = Math.ceil(rows.length / PAGE_SIZE)
    const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

    return (
        <div>
            <table className="RawSqlDebug__table">
                <thead>
                    <tr>
                        {columns.map((col, i) => (
                            <th key={i}>
                                <div>{col.name}</div>
                                <div className="text-xs text-muted font-normal">{col.type}</div>
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {pageRows.map((row, i) => (
                        <tr key={page * PAGE_SIZE + i}>
                            {row.map((val, j) => (
                                <Cell key={j} value={val} />
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
            {totalPages > 1 && (
                <div className="flex items-center justify-between p-2 border-t text-xs">
                    <span className="text-muted">
                        {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, rows.length)} of {rows.length}
                    </span>
                    <div className="flex gap-1">
                        <LemonButton size="xsmall" disabled={page === 0} onClick={() => setPage(page - 1)}>
                            Previous
                        </LemonButton>
                        <LemonButton size="xsmall" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
                            Next
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

function Cell({ value }: { value: any }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const isNull = value === null || value === undefined

    const formatted = isNull ? '' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)

    return (
        <td className={expanded ? '' : 'RawSqlDebug__cell--collapsed'} onClick={() => setExpanded(!expanded)}>
            {isNull ? <span className="text-muted italic">NULL</span> : formatted}
        </td>
    )
}

function QueryLogPanel({ entry, loading }: { entry: QueryLogEntry | null; loading: boolean }): JSX.Element {
    if (loading) {
        return <div className="text-muted p-4">Fetching query log from ClickHouse...</div>
    }

    if (!entry) {
        return (
            <LemonBanner type="info">
                Query log entry not yet available. ClickHouse may take a moment to flush the query_log.
            </LemonBanner>
        )
    }

    const data = entry.entry
    const dataSource = Object.entries(data).map(([key, value]) => ({ key, value }))

    return (
        <LemonTable
            dataSource={dataSource}
            columns={[
                {
                    title: 'Column',
                    dataIndex: 'key',
                    width: 250,
                    render: (_, row) => <span className="font-mono text-xs">{row.key}</span>,
                },
                {
                    title: 'Value',
                    dataIndex: 'value',
                    render: (_, row) => {
                        const val = row.value
                        if (val === null || val === undefined || val === '') {
                            return <span className="text-muted italic">—</span>
                        }
                        if (typeof val === 'object') {
                            return (
                                <span className="font-mono text-xs whitespace-pre-wrap break-all">
                                    {JSON.stringify(val, null, 2)}
                                </span>
                            )
                        }
                        return <span className="font-mono text-xs break-all">{String(val)}</span>
                    },
                },
            ]}
            size="small"
        />
    )
}
