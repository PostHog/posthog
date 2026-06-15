/**
 * `<TableView>` — read-only right-pane grid for one tabular-reference table
 * (the `@posthog/table-*` JSONL tables). The table list itself lives in the
 * memory file/folder tree (see `MemoryClassic`); this renders the rows of the
 * selected table.
 */

'use client'

import { useSessionTeamId } from '@/components/session-context'
import { readTable } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

import { RefreshIndicator } from './RefreshIndicator'

function cell(v: unknown): string {
    if (v === null || v === undefined) {
        return ''
    }
    if (typeof v === 'object') {
        return JSON.stringify(v)
    }
    return String(v)
}

export function TableView({ slug, name }: { slug: string; name: string }): React.ReactElement {
    const teamId = useSessionTeamId()!
    const rows = useResource(() => readTable(teamId, slug, name, { limit: 500 }), [teamId, slug, name], {
        pollMs: 10000,
    })

    if (rows.loading && !rows.data) {
        return <div className="p-6 text-sm text-muted-foreground">Loading…</div>
    }
    if (rows.error) {
        return <div className="p-6 text-sm text-destructive-foreground">Failed to load: {rows.error.message}</div>
    }
    const data = rows.data
    if (!data) {
        return <div className="p-6 text-sm text-muted-foreground">No data.</div>
    }
    const columns = Array.from(new Set(data.rows.flatMap((r) => Object.keys(r))))

    return (
        <div className="flex h-full flex-col">
            <header className="flex items-center justify-between gap-3 border-b border-border bg-muted/10 px-3 py-2">
                <code className="text-[0.8125rem] font-mono">{name}</code>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                        {data.returned} of {data.total} rows
                        {data.total > data.returned ? ` (first ${data.limit})` : ''}
                    </span>
                    <RefreshIndicator resource={rows} intervalMs={0} />
                </div>
            </header>
            <div className="min-h-0 flex-1 overflow-auto">
                {data.rows.length === 0 ? (
                    <div className="p-6 text-sm text-muted-foreground">Table is empty.</div>
                ) : (
                    <table className="w-full border-collapse text-[0.75rem]">
                        <thead className="sticky top-0 bg-muted/40">
                            <tr>
                                {columns.map((c) => (
                                    <th
                                        key={c}
                                        className="border-b border-border px-2 py-1 text-left font-mono font-medium"
                                    >
                                        {c}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {data.rows.map((r, i) => (
                                <tr key={i} className="even:bg-muted/10">
                                    {columns.map((c) => (
                                        <td
                                            key={c}
                                            className="max-w-[28rem] truncate border-b border-border/50 px-2 py-1 font-mono"
                                            title={cell(r[c])}
                                        >
                                            {cell(r[c])}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}
