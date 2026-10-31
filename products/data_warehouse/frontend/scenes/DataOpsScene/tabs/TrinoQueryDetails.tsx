import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import type { TrinoMonitoringQuery } from './managedWarehouseTrinoMonitoringLogic'
import { duration } from './trinoMonitoringFormat'

export function TrinoQueryDetails({ query }: { query: TrinoMonitoringQuery }): JSX.Element {
    const details: [string, string][] = [
        ['Source', query.source || 'Not set'],
        ['Queue time', duration(query.queued_ms)],
        ['CPU time', duration(query.cpu_ms)],
        ['Peak memory', humanizeBytes(query.peak_memory_bytes)],
        ['Rows read', humanFriendlyNumber(query.processed_input_rows)],
        ['Started', query.created_at ? humanFriendlyDetailedTime(query.created_at) : 'Unknown'],
    ]
    return (
        <div className="sticky left-0 max-w-[100cqw] space-y-3 p-3">
            <dl className="mb-0 flex flex-wrap gap-x-6 gap-y-2">
                {details.map(([label, value]) => (
                    <div key={label}>
                        <dt className="text-xs text-muted">{label}</dt>
                        <dd className="mb-0">{value}</dd>
                    </div>
                ))}
            </dl>
            <pre className="mb-0 whitespace-pre-wrap break-words text-xs">{query.query}</pre>
        </div>
    )
}
