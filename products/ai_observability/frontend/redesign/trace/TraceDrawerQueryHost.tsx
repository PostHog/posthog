import { useValues } from 'kea'
import { useMemo } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode } from '~/queries/schema/schema-general'

import { TraceDrawerHost } from './TraceDrawerHost'
import type { TraceDrawerListId } from './traceDrawerLists'
import { traceDrawerLogic } from './traceDrawerLogic'
import { TraceDrawerRowsSync } from './TraceDrawerRowsHost'
import { TraceListRow } from './traceListRows'

export interface TraceDrawerQueryHostProps {
    listId: TraceDrawerListId
    dataNodeKey: string
    query: DataTableNode['source']
    /** Needs a stable identity, because a new function maps every row again. */
    toRow: (result: unknown) => TraceListRow | null
}

function toRows(response: unknown, toRow: TraceDrawerQueryHostProps['toRow']): TraceListRow[] {
    const results = typeof response === 'object' && response && 'results' in response ? response.results : null
    if (!Array.isArray(results)) {
        return []
    }
    return results.flatMap((result) => {
        const row = toRow(result)
        return row ? [row] : []
    })
}

function TraceDrawerQueryRows({ listId, dataNodeKey, query, toRow }: TraceDrawerQueryHostProps): JSX.Element {
    const { response } = useValues(dataNodeLogic({ key: dataNodeKey, query }))
    const rows = useMemo(() => toRows(response, toRow), [response, toRow])

    return <TraceDrawerRowsSync listId={listId} rows={rows} />
}

// Render this as a sibling after DataTable, so that DataTable builds the logic with its full props. Subscribing in the
// list component would also rebuild the table context on each poll and re-render every row.
export function TraceDrawerQueryHost(props: TraceDrawerQueryHostProps): JSX.Element {
    const { isEnabled } = useValues(traceDrawerLogic({ listId: props.listId }))

    return (
        <>
            {isEnabled ? <TraceDrawerQueryRows {...props} /> : null}
            <TraceDrawerHost listId={props.listId} />
        </>
    )
}
