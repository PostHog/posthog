import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonBanner, LemonButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import {
    SqlScatterGraph,
    SqlScatterGraphProps,
} from '~/queries/nodes/DataVisualization/Components/Charts/SqlScatterGraph'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'

import { buildBIScatterSeries, keepBIScatterRows } from './biScatter'
import { biScatterLogic } from './biScatterLogic'

export interface BIScatterGraphProps extends SqlScatterGraphProps {
    query: BIVisualizationNode
    columns: string[]
    rows: unknown[][]
    chartKey: string
    onKeepOnly?: (records: Record<string, unknown>[]) => void
}

export function BIScatterGraph({
    query,
    columns,
    rows,
    chartKey,
    onKeepOnly,
    ...chartProps
}: BIScatterGraphProps): JSX.Element {
    const logic = biScatterLogic({
        chartKey: JSON.stringify([
            chartKey,
            query.source,
            chartProps.xData?.column.name,
            chartProps.yData.map(({ column, settings }) => [column.name, settings?.formatting?.style === 'percent']),
            query.chartSettings?.scatter?.xScale,
            query.chartSettings?.leftYAxisSettings?.scale,
        ]),
    })
    const { selected, mode, viewport, hiddenSeries } = useValues(logic)
    const { toggle, select, clear, setMode, setViewport, setHiddenSeries, toggleSeries } = useActions(logic)
    const { series, overBudget } = useMemo(() => {
        const series = buildBIScatterSeries(query, columns, rows, chartProps.xData, chartProps.yData)
        return { series: series ?? [], overBudget: series === null }
    }, [query, columns, rows, chartProps.xData, chartProps.yData])
    const selectedKeys = useMemo(() => new Set(selected), [selected])
    const hiddenKeys = useMemo(() => new Set(hiddenSeries), [hiddenSeries])
    const visibleSeries = useMemo(() => series.filter(({ key }) => !hiddenKeys.has(key)), [series, hiddenKeys])
    const visibleRowsByKey = useMemo(() => {
        const index = new Map<string, Set<number>>()
        for (const { points } of visibleSeries) {
            for (const { meta } of points) {
                if (meta?.rowKey !== undefined && meta.rowIndex !== undefined) {
                    let rowIndexes = index.get(meta.rowKey)
                    if (!rowIndexes) {
                        rowIndexes = new Set()
                        index.set(meta.rowKey, rowIndexes)
                    }
                    rowIndexes.add(meta.rowIndex)
                }
            }
        }
        return index
    }, [visibleSeries])
    const { selectedRecords, selectedCount } = useMemo(() => {
        if (overBudget || selectedKeys.size === 0) {
            return { selectedRecords: [], selectedCount: 0 }
        }
        const selectedRowIndexes: number[] = []
        let selectedCount = 0
        for (const key of selectedKeys) {
            const rowIndexes = visibleRowsByKey.get(key)
            if (rowIndexes) {
                selectedCount += rowIndexes.size
                if (selectedCount <= 200) {
                    selectedRowIndexes.push(...rowIndexes)
                }
            }
        }
        return {
            selectedCount,
            selectedRecords:
                selectedCount <= 200
                    ? selectedRowIndexes
                          .sort((a, b) => a - b)
                          .map((rowIndex) =>
                              Object.fromEntries(columns.map((column, index) => [column, rows[rowIndex][index]]))
                          )
                    : [],
        }
    }, [columns, rows, selectedKeys, visibleRowsByKey, overBudget])
    const selectionConfig = useMemo(
        () => keepBIScatterRows(query.config, selectedRecords),
        [query.config, selectedRecords]
    )
    const isPointHighlighted = useCallback<NonNullable<SqlScatterGraphProps['isPointHighlighted']>>(
        (point) => point.meta?.rowKey !== undefined && selectedKeys.has(point.meta.rowKey),
        [selectedKeys]
    )
    const chartSettings = useMemo(
        () => ({
            ...chartProps.chartSettings,
            showLegend: chartProps.chartSettings.showLegend ?? !!query.config.colorBy,
        }),
        [chartProps.chartSettings, query.config.colorBy]
    )
    if (overBudget) {
        return (
            <LemonBanner type="warning">
                Too many color groups to plot safely. Choose Single color, use a field with fewer distinct values, or
                narrow the worksheet filters.
            </LemonBanner>
        )
    }
    return (
        <div className="flex h-full w-full flex-1 min-h-0 min-w-0 flex-col">
            {onKeepOnly && (
                <div
                    className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-surface-primary px-3 py-2 text-xs"
                    data-attr="bi-scatter-selection"
                >
                    <LemonSelect
                        size="xsmall"
                        value={mode}
                        onChange={setMode}
                        options={[
                            { value: 'select', label: 'Select points' },
                            { value: 'zoom', label: 'Zoom area' },
                        ]}
                    />
                    <LemonTag
                        type={selectedCount ? 'highlight' : 'default'}
                        data-attr="bi-scatter-selection-count"
                        role="status"
                        aria-live="polite"
                    >
                        <span>{`${selectedCount} selected`}</span>
                    </LemonTag>
                    <LemonButton
                        size="small"
                        type="primary"
                        onClick={() => {
                            onKeepOnly(selectedRecords)
                            clear()
                        }}
                        disabledReason={
                            !selectedCount
                                ? 'Select points first'
                                : selectedCount > 200
                                  ? 'Select at most 200 points'
                                  : !query.config.rows.length && !query.config.columns.length
                                    ? 'Add a detail dimension first'
                                    : !selectionConfig
                                      ? 'This selection contains unsupported detail values or too many filter groups'
                                      : undefined
                        }
                        data-attr="bi-scatter-keep-only"
                    >
                        Keep only
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={clear}
                        disabledReason={!selected.length ? 'No points selected' : undefined}
                        data-attr="bi-scatter-clear-selection"
                    >
                        Clear selection
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        onClick={() => setViewport(null)}
                        disabledReason={!viewport ? 'Showing the full chart' : undefined}
                    >
                        Reset zoom
                    </LemonButton>
                    <span className="w-full text-secondary">
                        Click to toggle points or drag an area. Keep only changes worksheet filters; Undo restores them.
                        Missing coordinates are omitted; log axes require positive values.
                    </span>
                </div>
            )}
            <SqlScatterGraph
                {...chartProps}
                series={series}
                isPointHighlighted={isPointHighlighted}
                viewport={viewport}
                legendVisibility={{
                    hiddenKeys: hiddenSeries,
                    onToggleSeries: toggleSeries,
                    onSetHiddenSeries: setHiddenSeries,
                }}
                chartSettings={chartSettings}
                onPointClick={
                    onKeepOnly
                        ? (point) => {
                              if (point.meta?.rowKey !== undefined) {
                                  toggle(point.meta.rowKey)
                              }
                          }
                        : undefined
                }
                onAreaSelect={
                    onKeepOnly
                        ? (area) => {
                              if (mode === 'zoom') {
                                  setViewport(area)
                              } else {
                                  select(
                                      visibleSeries.flatMap((series) =>
                                          series.points
                                              .filter(
                                                  (point) =>
                                                      point.x >= area.x[0] &&
                                                      point.x <= area.x[1] &&
                                                      point.y >= area.y[0] &&
                                                      point.y <= area.y[1]
                                              )
                                              .flatMap((point) =>
                                                  point.meta?.rowKey === undefined ? [] : [point.meta.rowKey]
                                              )
                                      )
                                  )
                              }
                          }
                        : undefined
                }
            />
        </div>
    )
}
