import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { AxisSeriesSettings, dataVisualizationLogic, formatDataWithSettings } from '../../dataVisualizationLogic'
import { measureLabel } from '../../insightBuilder/builderLabels'
import { CompiledBuilderQuery, compileBuilderQuery } from '../../insightBuilder/compileBuilderQuery'
import { PivotCellValue, buildPivotData, pivotRowKey } from './pivotTableUtils'

const HEADER_CELL_CLASS = 'border border-border bg-surface-primary px-2 py-1 text-left font-medium'
const VALUE_CELL_CLASS = 'border border-border px-2 py-1 text-right tabular-nums'

function formatCell(value: PivotCellValue | undefined, settings?: AxisSeriesSettings): string {
    if (value === undefined || value === null) {
        return '–'
    }
    const formatted = formatDataWithSettings(value, settings)
    return typeof formatted === 'string' ? formatted : String(value)
}

export function PivotTable(): JSX.Element {
    const { response, columns, query, chartSettings } = useValues(dataVisualizationLogic)

    const builder = query.builder
    const rows: any[][] =
        response && 'results' in response ? response.results : response && 'result' in response ? response.result : []

    const columnIndexByName = useMemo(
        () =>
            columns.reduce(
                (acc, column) => {
                    acc[column.name] = column.dataIndex
                    return acc
                },
                {} as Record<string, number>
            ),
        [columns]
    )

    // Recomputing the compiler output guarantees the aliases match the executed SQL byte-for-byte
    const compiled: CompiledBuilderQuery | null = useMemo(() => {
        if (!builder?.enabled) {
            return null
        }
        try {
            return compileBuilderQuery(builder)
        } catch {
            return null
        }
    }, [builder])

    const pivotData = useMemo(() => {
        if (!compiled) {
            return null
        }
        return buildPivotData(rows ?? [], columnIndexByName, {
            rowAliases: compiled.rowAliases,
            columnAliases: compiled.columnAliases,
            valueAliases: compiled.valueAliases,
        })
    }, [compiled, rows, columnIndexByName])

    const settingsByAlias = useMemo(() => {
        const map: Record<string, AxisSeriesSettings | undefined> = {}
        for (const axis of chartSettings.yAxis ?? []) {
            map[axis.column] = axis.settings
        }
        return map
    }, [chartSettings.yAxis])

    if (!builder?.enabled || !compiled || !pivotData) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState
                    heading="Pivot tables are configured in Build mode"
                    detail="Add at least one Row and one Value in the SQL editor's Build mode."
                />
            </div>
        )
    }

    if (pivotData.rowKeys.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState heading="No results for this pivot" detail="" />
            </div>
        )
    }

    const rowHeaders = builder.rows.map((dim) => (dim.dateGrain ? `${dim.column} (${dim.dateGrain})` : dim.column))
    const valueLabels = builder.values.map(measureLabel)
    const hasColumnDims = compiled.columnAliases.length > 0
    const multiValue = compiled.valueAliases.length > 1
    const twoRowHeader = hasColumnDims && multiValue

    return (
        <div className="flex flex-col gap-2 p-2">
            {pivotData.duplicateCount > 0 && (
                <LemonBanner type="warning">
                    {`Some rows share the same Row/Column combination. Only the latest value is shown for ${
                        pivotData.duplicateCount
                    } duplicate cell${pivotData.duplicateCount === 1 ? '' : 's'}.`}
                </LemonBanner>
            )}
            <div className="overflow-auto">
                <table className="min-w-full border-collapse text-xs" data-attr="pivot-table">
                    <thead>
                        <tr>
                            {rowHeaders.map((header, index) => (
                                <th
                                    key={`row-header-${index}`}
                                    rowSpan={twoRowHeader ? 2 : 1}
                                    className={`${HEADER_CELL_CLASS} ${index === 0 ? 'sticky left-0 z-10' : ''}`}
                                >
                                    {header}
                                </th>
                            ))}
                            {hasColumnDims
                                ? pivotData.columnKeys.map((columnKey) => (
                                      <th
                                          key={`col-${columnKey}`}
                                          colSpan={multiValue ? valueLabels.length : 1}
                                          className={`${HEADER_CELL_CLASS} ${multiValue ? 'text-center' : ''}`}
                                      >
                                          {columnKey}
                                      </th>
                                  ))
                                : valueLabels.map((label) => (
                                      <th key={`value-${label}`} className={HEADER_CELL_CLASS}>
                                          {label}
                                      </th>
                                  ))}
                        </tr>
                        {twoRowHeader ? (
                            <tr>
                                {pivotData.columnKeys.flatMap((columnKey) =>
                                    valueLabels.map((label, valueIndex) => (
                                        <th key={`col-${columnKey}-value-${valueIndex}`} className={HEADER_CELL_CLASS}>
                                            {label}
                                        </th>
                                    ))
                                )}
                            </tr>
                        ) : null}
                    </thead>
                    <tbody>
                        {pivotData.rowKeys.map((rowTuple) => {
                            const rowKey = pivotRowKey(rowTuple)
                            return (
                                <tr key={rowKey}>
                                    {rowTuple.map((label, index) => (
                                        <th
                                            key={`dim-${index}`}
                                            className={`${HEADER_CELL_CLASS} font-normal ${
                                                index === 0 ? 'sticky left-0 z-10' : ''
                                            }`}
                                        >
                                            {label}
                                        </th>
                                    ))}
                                    {pivotData.columnKeys.flatMap((columnKey) =>
                                        compiled.valueAliases.map((alias, valueIndex) => (
                                            <td key={`${columnKey}-${alias}`} className={VALUE_CELL_CLASS}>
                                                {formatCell(
                                                    pivotData.cells[rowKey]?.[columnKey]?.[valueIndex],
                                                    settingsByAlias[alias]
                                                )}
                                            </td>
                                        ))
                                    )}
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
