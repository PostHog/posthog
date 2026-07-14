import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyLargeNumber, humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import { CachePartitionRow, CacheTableStats, queryPerformanceLogic } from './queryPerformanceLogic'

// Partitions are keyed by toYYYYMMDD(expires_at), so a partition id is the day its rows expire.
const partitionToISO = (partition: string): string =>
    `${partition.slice(0, 4)}-${partition.slice(4, 6)}-${partition.slice(6, 8)}`

const formatPartitionDay = (partition: string): string => dayjs(partitionToISO(partition)).format('MMM D')

// TTL uses ttl_only_drop_parts=1, so whole partitions drop once their expiry day passes. A partition
// dated before today is expired data still on disk, waiting for the TTL merge to drop it.
function ttlStatus(partition: string): { label: string; type: LemonTagType } {
    const today = dayjs().format('YYYYMMDD')
    if (partition < today) {
        return { label: 'Expired, awaiting drop', type: 'danger' }
    }
    if (partition === today) {
        return { label: 'Drops today', type: 'warning' }
    }
    const days = dayjs(partitionToISO(partition)).diff(dayjs().startOf('day'), 'day')
    return { label: `Drops in ${days}d`, type: 'muted' }
}

// "experiment_exposures_preaggregated" -> "Exposures", "experiment_metric_events_preaggregated" -> "Metric events"
function tableLabel(table: string): string {
    const short = table
        .replace(/^experiment_/, '')
        .replace(/_preaggregated$/, '')
        .replace(/_/g, ' ')
    return short.charAt(0).toUpperCase() + short.slice(1)
}

function TableCard({ table }: { table: CacheTableStats }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex-1 min-w-72">
            <div className="font-mono text-xs text-muted">{table.table}</div>
            <div className="text-xl font-semibold mt-1">
                {humanFriendlyLargeNumber(table.total_rows)} rows · {humanizeBytes(table.bytes_on_disk)}
            </div>
            <div className="text-xs text-muted mt-1">
                {humanFriendlyNumber(table.active_parts)} active parts · {table.partition_count} partition days
            </div>
            <div className="text-xs text-muted">
                {table.oldest_partition && table.newest_partition
                    ? `Expiry span: ${formatPartitionDay(table.oldest_partition)} → ${formatPartitionDay(
                          table.newest_partition
                      )}`
                    : 'No active parts'}
            </div>
        </LemonCard>
    )
}

export function CacheHealth(): JSX.Element {
    const { cacheHealth, cacheHealthLoading, cachePartitionRows } = useValues(queryPerformanceLogic)
    const { loadCacheHealth } = useActions(queryPerformanceLogic)

    const tables = cacheHealth?.tables ?? []

    const partitionColumns: LemonTableColumns<CachePartitionRow> = [
        {
            title: 'Expiry day',
            width: 220,
            render: function ExpiryDay(_, row) {
                const { label, type } = ttlStatus(row.partition)
                return (
                    <div className="flex items-center gap-2">
                        <span className="font-mono text-xs">{formatPartitionDay(row.partition)}</span>
                        <LemonTag type={type}>{label}</LemonTag>
                    </div>
                )
            },
        },
        ...tables.flatMap((table): LemonTableColumns<CachePartitionRow> => {
            const label = tableLabel(table.table)
            return [
                {
                    title: `${label} rows`,
                    render: function Rows(_, row) {
                        const stats = row.perTable[table.table]
                        return (
                            <span className="font-mono">
                                {stats ? humanFriendlyNumber(stats.rows) : <span className="text-muted">–</span>}
                            </span>
                        )
                    },
                },
                {
                    title: `${label} size`,
                    render: function Size(_, row) {
                        const stats = row.perTable[table.table]
                        return (
                            <span className="font-mono">
                                {stats ? humanizeBytes(stats.bytes_on_disk) : <span className="text-muted">–</span>}
                            </span>
                        )
                    },
                },
            ]
        }),
    ]

    return (
        <>
            <div className="flex items-center justify-between gap-2 mb-2">
                <p className="text-muted text-sm mb-0">
                    Physical footprint of the experiment preaggregation tables (active parts across all shards, from
                    ClickHouse system.parts).
                </p>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => loadCacheHealth()}
                    disabledReason={cacheHealthLoading ? 'Loading...' : undefined}
                >
                    Refresh
                </LemonButton>
            </div>
            <div className="flex flex-wrap gap-4 mb-4">
                {!cacheHealth && cacheHealthLoading
                    ? [0, 1].map((i) => (
                          <LemonCard key={i} hoverEffect={false} className="flex-1 min-w-72">
                              <LemonSkeleton className="h-4 w-1/2" />
                              <LemonSkeleton className="h-6 w-2/3 mt-2" />
                              <LemonSkeleton className="h-3 w-1/2 mt-2" />
                              <LemonSkeleton className="h-3 w-1/3 mt-1" />
                          </LemonCard>
                      ))
                    : tables.map((table) => <TableCard key={table.table} table={table} />)}
            </div>
            <h3>Partition breakdown by expiry day</h3>
            <LemonTable
                size="small"
                columns={partitionColumns}
                dataSource={cachePartitionRows}
                loading={cacheHealthLoading}
                emptyState="No active parts found"
                className="overflow-visible! flex-none! mb-8"
            />
        </>
    )
}
