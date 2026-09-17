import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyLargeNumber, humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import { CacheGrowthResponse, CachePartitionRow, CacheTableStats, queryPerformanceLogic } from './queryPerformanceLogic'

const GROWTH_RANGE_OPTIONS = [
    { label: '48h', hours: 48 },
    { label: '7d', hours: 168 },
    { label: '14d', hours: 336 },
    { label: '21d', hours: 504 },
]

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

// The tables self-clean only while TTL merges keep dropping expired partitions. Any partition
// dated before today means that stopped, so it gets a headline verdict instead of a table row
// the reader has to scan for.
function TtlVerdictBanner({ tables }: { tables: CacheTableStats[] }): JSX.Element | null {
    if (tables.length === 0) {
        return null
    }
    const readable = tables.filter((table) => !table.unavailable)
    const unavailable = tables.filter((table) => table.unavailable)
    const today = dayjs().format('YYYYMMDD')
    const expired = readable.flatMap((table) => table.partitions.filter((partition) => partition.partition < today))
    if (expired.length > 0) {
        const days = new Set(expired.map((partition) => partition.partition))
        const bytes = expired.reduce((sum, partition) => sum + partition.bytes_on_disk, 0)
        const oldest = [...days].sort()[0]
        return (
            <LemonBanner type="error" className="mb-4">
                Expired data from {days.size} {days.size === 1 ? 'day' : 'days'} ({humanizeBytes(bytes)}) is still on
                disk, oldest from {formatPartitionDay(oldest)}. ClickHouse is not dropping expired partitions. Check TTL
                merges on the cluster.
            </LemonBanner>
        )
    }
    // A green verdict from partial data would hide the exact failure it exists to surface,
    // so an unreadable table degrades the verdict to unknown.
    if (unavailable.length > 0) {
        return (
            <LemonBanner type="warning" className="mb-4">
                TTL status is unknown for {unavailable.map((table) => tableLabel(table.table)).join(' and ')}:
                system.parts could not be read. No expired data in the tables that were checked.
            </LemonBanner>
        )
    }
    return (
        <LemonBanner type="success" className="mb-4">
            TTL cleanup is keeping up. No expired data is waiting to be dropped.
        </LemonBanner>
    )
}

// "experiment_exposures_preaggregated" -> "exposures" — the key the backend uses for growth series
// (it comes from the experiment_precompute_table query tag on build INSERTs).
const growthKey = (table: string): string => table.replace(/^experiment_/, '').replace(/_preaggregated$/, '')

// "experiment_exposures_preaggregated" -> "Exposures", "experiment_metric_events_preaggregated" -> "Metric events"
function tableLabel(table: string): string {
    const short = growthKey(table).replace(/_/g, ' ')
    return short.charAt(0).toUpperCase() + short.slice(1)
}

function GrowthChart({
    title,
    growth,
    data,
    formatValue,
}: {
    title: string
    growth: CacheGrowthResponse
    data: number[]
    formatValue?: (value: number) => string
}): JSX.Element {
    const theme = useChartTheme()
    return (
        <div>
            <div className="text-xs text-muted mb-1">{title}</div>
            {/* Flex column: the chart root is `flex-1` and only gets height from a flex parent. */}
            <div className="h-32 flex flex-col">
                <TimeSeriesBarChart
                    series={[{ key: 'value', label: title, data }]}
                    labels={growth.buckets}
                    theme={theme}
                    config={{
                        xAxis: { timezone: 'UTC', interval: growth.interval },
                        yAxis: formatValue ? { tickFormatter: formatValue } : { format: 'short' },
                        tooltip: formatValue ? { valueFormatter: formatValue } : undefined,
                        showGrid: true,
                    }}
                />
            </div>
        </div>
    )
}

function TableCard({ table, growth }: { table: CacheTableStats; growth: CacheGrowthResponse | null }): JSX.Element {
    if (table.unavailable) {
        return (
            <LemonCard hoverEffect={false} className="flex-1 min-w-72">
                <div className="font-mono text-xs text-muted">{table.table}</div>
                <div className="text-xl font-semibold mt-1">Unavailable</div>
                <div className="text-xs text-muted mt-1">Couldn't read system.parts from this table's cluster</div>
            </LemonCard>
        )
    }
    const series = growth?.tables[growthKey(table.table)]
    const per = growth?.interval === 'hour' ? 'per hour' : 'per day'
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
            {growth && series ? (
                <div className="flex flex-col gap-3 mt-3">
                    <GrowthChart title={`Rows written ${per}`} growth={growth} data={series.written_rows} />
                    <GrowthChart
                        title={`Data written ${per} (uncompressed)`}
                        growth={growth}
                        data={series.written_bytes}
                        formatValue={humanizeBytes}
                    />
                </div>
            ) : (
                <div className="flex flex-col gap-3 mt-3">
                    <LemonSkeleton className="h-32 w-full" />
                    <LemonSkeleton className="h-32 w-full" />
                </div>
            )}
        </LemonCard>
    )
}

export function CacheHealth(): JSX.Element {
    const { cacheHealth, cacheHealthLoading, cachePartitionRows, cacheGrowth, cacheGrowthHoursBack } =
        useValues(queryPerformanceLogic)
    const { loadCacheHealth, loadCacheGrowth, setCacheGrowthHoursBack } = useActions(queryPerformanceLogic)

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
                    Physical footprint of the experiment preaggregation tables (totals from ClickHouse system.parts,
                    growth from the archived build inserts).
                </p>
                <div className="flex items-center gap-2">
                    {GROWTH_RANGE_OPTIONS.map(({ label, hours }) => (
                        <LemonButton
                            key={hours}
                            type={cacheGrowthHoursBack === hours ? 'primary' : 'tertiary'}
                            size="small"
                            onClick={() => setCacheGrowthHoursBack(hours)}
                        >
                            {label}
                        </LemonButton>
                    ))}
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => {
                            loadCacheHealth()
                            loadCacheGrowth()
                        }}
                        disabledReason={cacheHealthLoading ? 'Loading...' : undefined}
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>
            {cacheHealth ? <TtlVerdictBanner tables={tables} /> : null}
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
                    : tables.map((table) => <TableCard key={table.table} table={table} growth={cacheGrowth} />)}
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
