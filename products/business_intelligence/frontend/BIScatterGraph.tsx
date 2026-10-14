import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import {
    SqlScatterGraph,
    SqlScatterGraphProps,
} from '~/queries/nodes/DataVisualization/Components/Charts/SqlScatterGraph'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'

import { buildBIScatterSeries, getBIScatterRowKey, keepBIScatterRows } from './biScatter'
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
    const logic = biScatterLogic({ chartKey: `${chartKey}:${JSON.stringify(query.source)}` })
    const { selected, mode, viewport } = useValues(logic)
    const { toggle, select, clear, setMode, setViewport } = useActions(logic)
    const series = useMemo(
        () => buildBIScatterSeries(query, columns, rows, chartProps.xData, chartProps.yData),
        [query, columns, rows, chartProps.xData, chartProps.yData]
    )
    const selectedRecords = rows
        .filter((row) => selected.includes(getBIScatterRowKey(query.config, columns, row)))
        .map((row) => Object.fromEntries(columns.map((column, index) => [column, row[index]])))
    const selectionConfig = keepBIScatterRows(query.config, selectedRecords)
    const highlighted = useMemo(
        () =>
            selected.length
                ? series.map((series) => ({
                      ...series,
                      points: series.points.map((point) => ({
                          ...point,
                          radius: point.meta?.rowKey !== undefined && selected.includes(point.meta.rowKey) ? 7 : 3,
                      })),
                  }))
                : series,
        [series, selected]
    )
    return (
        <div className="flex h-full w-full flex-1 min-h-0 min-w-0 flex-col">
            {onKeepOnly && (
                <div className="flex flex-wrap items-center gap-2 px-3 py-1 text-xs" data-attr="bi-scatter-selection">
                    <LemonSelect
                        size="xsmall"
                        value={mode}
                        onChange={setMode}
                        options={[
                            { value: 'select', label: 'Select points' },
                            { value: 'zoom', label: 'Zoom area' },
                        ]}
                    />
                    <span>{selectedRecords.length} selected</span>
                    <LemonButton
                        size="xsmall"
                        onClick={() => {
                            onKeepOnly(selectedRecords)
                            clear()
                        }}
                        disabledReason={
                            !selectedRecords.length
                                ? 'Select points first'
                                : selectedRecords.length > 200
                                  ? 'Select at most 200 points'
                                  : !query.config.rows.length && !query.config.columns.length
                                    ? 'Add a detail dimension first'
                                    : !selectionConfig
                                      ? 'Simplify the existing filter groups before keeping this selection'
                                      : undefined
                        }
                        data-attr="bi-scatter-keep-only"
                    >
                        Keep only
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        onClick={clear}
                        disabledReason={!selected.length ? 'No points selected' : undefined}
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
                    <span className="text-secondary">
                        Click to toggle points or drag an area. Keep only changes worksheet filters; Undo restores them.
                        Missing coordinates are omitted; log axes require positive values.
                    </span>
                </div>
            )}
            <SqlScatterGraph
                {...chartProps}
                series={highlighted}
                viewport={viewport}
                chartSettings={{
                    ...chartProps.chartSettings,
                    showLegend: chartProps.chartSettings.showLegend ?? !!query.config.colorBy,
                }}
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
                                      series.flatMap((series) =>
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
