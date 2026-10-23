import { LemonTable, type LemonTableColumns } from '@posthog/lemon-ui'

import { formatMetricValue } from 'products/metrics/frontend/panels/metricsUnits'

import {
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
    WidgetLoadingState,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'

export type MetricsTableResultColumn = {
    label: string
    aggregation: string
    unit?: string | null
}

export type MetricsTableResultRow = {
    key: string
    values: (number | null)[]
    sparklines: (number | null)[][]
}

export type MetricsTableWidgetResult = {
    needsConfiguration?: boolean
    groupBy?: string | null
    columns?: MetricsTableResultColumn[]
    rows?: MetricsTableResultRow[]
    totalCount?: number
    hasMore?: boolean
}

const WIDGET_LIST_COUNT_ROWS = { singular: 'row', plural: 'rows' }
const SPARKLINE_WIDTH = 96
const SPARKLINE_HEIGHT = 24

/** An SVG line instead of a chart instance, so a table with 100 rows stays cheap to render. */
function MetricsTableSparkline({ points, max }: { points: (number | null)[]; max: number }): JSX.Element | null {
    const values = points.map((point) => point ?? 0)
    if (values.length < 2) {
        return null
    }
    const step = SPARKLINE_WIDTH / (values.length - 1)
    const scale = max > 0 ? (SPARKLINE_HEIGHT - 2) / max : 0
    const line = values
        .map((value, index) => `${(index * step).toFixed(1)},${(SPARKLINE_HEIGHT - 1 - value * scale).toFixed(1)}`)
        .join(' ')
    return (
        <svg
            width={SPARKLINE_WIDTH}
            height={SPARKLINE_HEIGHT}
            viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`}
            className="shrink-0 text-accent"
            aria-hidden
        >
            <polyline
                points={`0,${SPARKLINE_HEIGHT} ${line} ${SPARKLINE_WIDTH},${SPARKLINE_HEIGHT}`}
                className="fill-current opacity-10"
            />
            <polyline points={line} fill="none" stroke="currentColor" strokeWidth={1.5} />
        </svg>
    )
}

/** The peak of each column across all rows, so the sparklines in one column share a scale. */
function columnPeaks(rows: MetricsTableResultRow[], columnCount: number): number[] {
    return Array.from({ length: columnCount }, (_, index) =>
        Math.max(0, ...rows.flatMap((row) => (row.sparklines[index] ?? []).map((point) => point ?? 0)))
    )
}

export function MetricsTableView({
    groupBy,
    columns,
    rows,
}: {
    groupBy: string
    columns: MetricsTableResultColumn[]
    rows: MetricsTableResultRow[]
}): JSX.Element {
    const peaks = columnPeaks(rows, columns.length)
    const tableColumns: LemonTableColumns<MetricsTableResultRow> = [
        {
            key: 'key',
            title: groupBy,
            render: (_, row) => (
                <span className="font-mono text-xs truncate block max-w-[24rem]" title={row.key}>
                    {row.key}
                </span>
            ),
        },
        ...columns.map((column, index) => ({
            key: `column-${index}`,
            title: column.label,
            align: 'right' as const,
            render: (_: unknown, row: MetricsTableResultRow) => {
                const value = row.values[index]
                return (
                    <div className="flex items-center justify-end gap-3">
                        <MetricsTableSparkline points={row.sparklines[index] ?? []} max={peaks[index]} />
                        <span className="tabular-nums w-28 shrink-0 text-right">
                            {value == null ? '–' : formatMetricValue(value, column.unit ?? undefined)}
                        </span>
                    </div>
                )
            },
        })),
    ]
    return (
        <LemonTable
            dataSource={rows}
            columns={tableColumns}
            rowKey="key"
            size="small"
            embedded
            data-attr="metrics-table-widget-table"
        />
    )
}

export function MetricsTableWidget({ result, loading }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as MetricsTableWidgetResult | null | undefined

    if (loading) {
        return <WidgetLoadingState rowCount={6} />
    }

    if (!payload || payload.needsConfiguration) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div className="flex max-w-sm flex-col items-center gap-1 px-2 text-balance">
                        <p className="m-0 text-base font-semibold text-primary">Pick a label and metrics</p>
                        <p className="m-0 text-sm text-muted">
                            Open the widget settings. Choose a label, such as http.route, and up to 4 metrics. The table
                            shows one row for each value of the label.
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    const rows = payload.rows ?? []
    if (rows.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div className="flex max-w-sm flex-col items-center gap-1 px-2 text-balance">
                        <p className="m-0 text-base font-semibold text-primary">No metrics found</p>
                        <p className="m-0 text-sm text-muted">
                            No series had the {payload.groupBy} label in this date range. Check the metric names or try
                            a longer date range.
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <MetricsTableView groupBy={payload.groupBy ?? ''} columns={payload.columns ?? []} rows={rows} />
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={rows.length}
                    totalCount={payload.totalCount}
                    noun={WIDGET_LIST_COUNT_ROWS}
                    hasMore={payload.hasMore}
                    dataAttr="metrics-table-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
