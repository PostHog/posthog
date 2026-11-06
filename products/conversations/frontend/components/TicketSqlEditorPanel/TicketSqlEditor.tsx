import { useActions, useValues } from 'kea'

import { IconPlay } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { DEFAULT_TICKET_SQL_QUERY, ticketSqlEditorLogic } from './ticketSqlEditorLogic'

function formatCell(value: unknown): JSX.Element {
    if (value === null || value === undefined) {
        return <span className="text-muted-alt">null</span>
    }
    return (
        <span className="whitespace-nowrap">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
    )
}

export function TicketSqlEditor({ personId, distinctId }: { personId: string; distinctId: string }): JSX.Element {
    const logic = ticketSqlEditorLogic({ personId, distinctId })
    const { editorQuery, placeholders, result, resultLoading, queryError } = useValues(logic)
    const { setQueryInput, runQuery, resetQuery } = useActions(logic)

    const columns: LemonTableColumns<unknown[]> = (result?.columns ?? []).map((column, index) => ({
        key: `${index}-${column}`,
        title: column,
        render: (_, row) => formatCell(row[index]),
    }))

    return (
        <div className="space-y-2">
            <CodeEditorResizeable
                queryKey={`ticketSqlEditor/${personId}`}
                language="hogQL"
                value={editorQuery}
                onChange={(value) => setQueryInput(value ?? '')}
                onPressCmdEnter={(value) => {
                    if (value.trim() && !resultLoading) {
                        runQuery(value)
                    }
                }}
                // Placeholders are validated as globals, so {person_id} and {distinct_id} are not flagged as errors.
                globals={placeholders}
                minHeight="6rem"
                maxHeight="20rem"
                options={{
                    minimap: { enabled: false },
                    wordWrap: 'on',
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
                    fixedOverflowWidgets: true,
                }}
            />
            <div className="text-xs text-secondary">
                Use <code>{'{person_id}'}</code> and <code>{'{distinct_id}'}</code> to query this ticket's customer.
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={resetQuery}
                    disabledReason={editorQuery === DEFAULT_TICKET_SQL_QUERY ? 'This is the default query' : null}
                    data-attr="ticket-sidebar-sql-editor-reset"
                >
                    Reset to default
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="xsmall"
                    icon={<IconPlay />}
                    onClick={() => runQuery(editorQuery)}
                    loading={resultLoading}
                    disabledReason={!editorQuery.trim() ? 'Write a query first' : null}
                    data-attr="ticket-sidebar-sql-editor-run"
                >
                    Run
                </LemonButton>
            </div>
            {resultLoading && !result ? (
                <div className="text-muted-alt text-xs">Running query...</div>
            ) : queryError ? (
                <LemonBanner type="error">{queryError}</LemonBanner>
            ) : !result ? (
                <div className="text-muted-alt text-xs">Run the query to see results.</div>
            ) : result.rows.length === 0 ? (
                <div className="text-muted-alt text-xs">The query returned no rows.</div>
            ) : (
                <div className="max-h-96 overflow-auto" translate="no">
                    <LemonTable size="small" columns={columns} dataSource={result.rows} loading={resultLoading} />
                </div>
            )}
        </div>
    )
}
