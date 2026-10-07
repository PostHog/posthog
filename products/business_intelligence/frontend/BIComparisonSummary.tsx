import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { ChartSettings } from '~/queries/schema/schema-general'

import { BIComparisonRow, buildBIComparisonRows, getBIComparisonValues } from './biComparisonResults'
import { formatBIMeasure, getBIResultMeasures } from './biResultPresentation'

export function BIComparisonSummary({
    config,
    columns,
    results,
    chartSettings,
    card = false,
    onInspect,
}: {
    config: BIConfig
    columns: string[]
    results: unknown[][]
    chartSettings?: ChartSettings
    card?: boolean
    onInspect?: (record: Record<string, unknown>) => void
}): JSX.Element {
    const rows = buildBIComparisonRows(config, columns, results)
    const measures = getBIResultMeasures(config, chartSettings)
    const dimensions = [...config.rows, ...config.columns]
    const summaries = [
        { key: 'current' as const, label: 'Current' },
        { key: 'previous' as const, label: config.compareFilter?.compare_to ? 'Comparison' : 'Previous' },
        { key: 'change' as const, label: 'Absolute change' },
        { key: 'percent' as const, label: '% change' },
    ]
    const cell = (
        row: BIComparisonRow,
        measure: (typeof measures)[number],
        key: (typeof summaries)[number]['key']
    ): JSX.Element => {
        const values = getBIComparisonValues(row, measure.column)
        const label = formatBIMeasure(
            values[key],
            key === 'percent' ? { formatting: { style: 'percent', decimalPlaces: 1 } } : measure.settings
        )
        const record = key === 'current' ? row.current : key === 'previous' ? row.previous : undefined
        return record && onInspect ? (
            <LemonButton
                size="xsmall"
                noPadding={card}
                type="tertiary"
                className="justify-end !text-inherit"
                data-attr="bi-comparison-inspect"
                onClick={() => onInspect(record)}
                tooltip="Explore this period"
            >
                <span className={card ? (key === 'current' ? 'text-3xl font-semibold' : 'text-xl') : undefined}>
                    {label}
                </span>
            </LemonButton>
        ) : (
            <span
                title={
                    key === 'percent' && values.previous === 0
                        ? 'Percentage change is undefined when the previous value is zero'
                        : undefined
                }
            >
                {label}
            </span>
        )
    }
    if (card) {
        return (
            <div className="flex flex-col gap-4 p-4 w-full min-w-0" data-attr="bi-comparison-kpi">
                {(rows.length ? rows : [{ key: 'empty', dimensions: [] }]).flatMap((row) =>
                    measures.map((measure) => (
                        <div key={`${row.key}:${measure.column}`} className="flex flex-col gap-2">
                            {row.dimensions.length > 0 && (
                                <div className="text-xs text-secondary break-words">
                                    {row.dimensions
                                        .map(
                                            (value, index) => `${dimensions[index].name}: ${String(value ?? '(empty)')}`
                                        )
                                        .join(' · ')}
                                </div>
                            )}
                            <div className="text-sm font-medium">{measure.label}</div>
                            <div className="flex flex-wrap gap-x-8 gap-y-4">
                                {summaries.map(({ key, label }) => (
                                    <div key={key} className="min-w-0 flex flex-col gap-1">
                                        <span className="text-xs text-secondary">{label}</span>
                                        <span className={key === 'current' ? 'text-3xl font-semibold' : 'text-xl'}>
                                            {cell(row, measure, key)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))
                )}
            </div>
        )
    }
    return (
        <div className="p-2 w-full min-w-0" data-attr="bi-comparison-table">
            <LemonTable<BIComparisonRow>
                dataSource={rows}
                rowKey="key"
                size="small"
                uppercaseHeader={false}
                useURLForSorting={false}
                emptyState="No results for these periods"
                columns={[
                    ...(dimensions.length
                        ? [
                              {
                                  children: dimensions.map((field, index) => ({
                                      key: field.id,
                                      title: field.name,
                                      render: (_: unknown, row: BIComparisonRow) =>
                                          String(row.dimensions[index] ?? '(empty)'),
                                  })),
                              },
                          ]
                        : []),
                    ...measures.map((measure) => ({
                        title: measure.label,
                        children: summaries.map(({ key, label }) => ({
                            key: `${measure.column}:${key}`,
                            title: label,
                            align: 'right' as const,
                            render: (_: unknown, row: BIComparisonRow) => cell(row, measure, key),
                        })),
                    })),
                ]}
            />
        </div>
    )
}
