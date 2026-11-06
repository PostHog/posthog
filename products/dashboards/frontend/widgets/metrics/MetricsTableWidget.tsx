import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonTable, type LemonTableColumns } from '@posthog/lemon-ui'

import {
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
    WidgetLoadingState,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import {
    type MetricsTableSparklineDomain,
    metricsTableColumnFormatters,
    metricsTableSparklineCoordinates,
    metricsTableSparklineDomains,
} from './metricsTableColumnScales'
import { MetricsTableDrilldownModal } from './MetricsTableDrilldownModal'
import { parseMetricsTableWidgetConfig } from './metricsTableWidgetConfigValidation'

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
    /** Set when the metrics query refused the config, with the reason to show. */
    queryError?: string | null
}

const WIDGET_LIST_COUNT_ROWS = { singular: 'row', plural: 'rows' }
const SPARKLINE_WIDTH = 72
const SPARKLINE_HEIGHT = 24

/** An SVG line instead of a chart instance, so a table with 100 rows stays cheap to render. */
function MetricsTableSparkline({
    points,
    domain,
}: {
    points: (number | null)[]
    domain: MetricsTableSparklineDomain
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    const coordinates = metricsTableSparklineCoordinates(points, domain, {
        width: SPARKLINE_WIDTH,
        height: SPARKLINE_HEIGHT,
    })
    const line = coordinates.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
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

export type MetricsTableSelection = {
    selected: string[]
    onToggle: (key: string) => void
    onOpen: (keys: string[]) => void
}

export function MetricsTableView({
    groupBy,
    columns,
    rows,
    selection,
}: {
    groupBy: string
    columns: MetricsTableResultColumn[]
    rows: MetricsTableResultRow[]
    /** Without it, the table is read-only, as in the add-widget preview. */
    selection?: MetricsTableSelection
}): JSX.Element {
    const domains = metricsTableSparklineDomains(rows, columns.length)
    const formatters = metricsTableColumnFormatters(rows, columns)
    const tableColumns: LemonTableColumns<MetricsTableResultRow> = [
        ...(selection
            ? [
                  {
                      key: 'select',
                      width: 0,
                      render: (_: unknown, row: MetricsTableResultRow) => (
                          <LemonCheckbox
                              checked={selection.selected.includes(row.key)}
                              onChange={() => selection.onToggle(row.key)}
                              aria-label={`Select ${row.key}`}
                          />
                      ),
                  },
              ]
            : []),
        {
            key: 'key',
            title: groupBy,
            render: (_, row) =>
                selection ? (
                    <LemonButton
                        size="xsmall"
                        className="font-mono max-w-[24rem]"
                        onClick={() => selection.onOpen([row.key])}
                        tooltip="Open full charts"
                        data-attr="metrics-table-widget-open-row"
                    >
                        <span className="truncate">{row.key}</span>
                    </LemonButton>
                ) : (
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
                    <div className="flex items-center justify-end gap-2">
                        <MetricsTableSparkline points={row.sparklines[index] ?? []} domain={domains[index]} />
                        <span className="tabular-nums min-w-24 shrink-0 whitespace-nowrap text-right">
                            {value == null ? '–' : formatters[index](value)}
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

export function MetricsTableWidget({ result, loading, config, tileId }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as MetricsTableWidgetResult | null | undefined
    const [selected, setSelected] = useState<string[]>([])
    const [openKeys, setOpenKeys] = useState<string[]>([])

    const openCharts = (keys: string[]): void => {
        setOpenKeys(keys)
        posthog.capture('dashboard widget open metrics charts clicked', {
            widget_type: 'metrics_table',
            tile_id: tileId,
            row_count: keys.length,
        })
    }
    const selection: MetricsTableSelection = {
        selected,
        onToggle: (key) =>
            setSelected((current) =>
                current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
            ),
        onOpen: openCharts,
    }

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

    if (payload.queryError) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div className="flex max-w-sm flex-col items-center gap-1 px-2 text-balance">
                        <p className="m-0 text-base font-semibold text-primary">This table can't load</p>
                        <p className="m-0 text-sm text-muted">{payload.queryError}</p>
                        <p className="m-0 text-sm text-muted">
                            Try a shorter date range, a label with fewer values, or a filter in the widget settings.
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
                <MetricsTableView
                    groupBy={payload.groupBy ?? ''}
                    columns={payload.columns ?? []}
                    rows={rows}
                    selection={selection}
                />
            </WidgetCardContent>
            <WidgetContentFooter className="items-center gap-2">
                {selected.length > 0 ? (
                    <>
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            onClick={() => openCharts(selected)}
                            data-attr="metrics-table-widget-open-selected"
                        >
                            Open {selected.length} in full charts
                        </LemonButton>
                        <LemonButton size="xsmall" onClick={() => setSelected([])}>
                            Clear
                        </LemonButton>
                    </>
                ) : null}
                <WidgetListCount
                    shown={rows.length}
                    totalCount={payload.totalCount}
                    noun={WIDGET_LIST_COUNT_ROWS}
                    hasMore={payload.hasMore}
                    dataAttr="metrics-table-widget-count"
                />
            </WidgetContentFooter>
            <MetricsTableDrilldownModal
                config={parseMetricsTableWidgetConfig(config)}
                keys={openKeys}
                onClose={() => setOpenKeys([])}
            />
        </>
    )
}
