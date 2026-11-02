/* eslint-disable react/forbid-dom-props -- swatch color and the content-sized column widths are dynamic values */
import React, { useMemo, useState } from 'react'

import { buildYTickFormatter } from '../../utils/y-formatters'
import type { LegendProps, LegendValue } from './Legend'

const DEFAULT_HEADERS: Record<'label' | LegendValue, string> = {
    label: 'Name',
    mean: 'Mean',
    min: 'Min',
    max: 'Max',
    first: 'First',
    last: 'Last',
    sum: 'Total',
}

const defaultFormatValue = buildYTickFormatter({})

type SortKey = 'label' | LegendValue

/** The value-column form of {@link Legend}: one row per series with its summaries as columns,
 *  sortable by clicking a header. Rows click and dim exactly like the list legend. */
export function LegendTable({
    items,
    values,
    formatValue = defaultFormatValue,
    sortBy,
    sortDescending = sortBy !== 'label',
    columnLabels,
    onItemClick,
    hiddenKeys,
    className,
    dataAttr,
    renderItem,
}: Omit<LegendProps, 'orientation' | 'align' | 'values'> & { values: LegendValue[] }): React.ReactElement {
    const headers = { ...DEFAULT_HEADERS, ...columnLabels }
    const [sort, setSort] = useState<{ key: SortKey; descending: boolean } | null>(
        sortBy ? { key: sortBy, descending: sortDescending } : null
    )

    const cells = useMemo(
        () =>
            new Map(
                items.map((item) => [
                    item.key,
                    values.map((v) => {
                        const value = item.values?.[v]
                        return value == null ? '' : formatValue(value, item)
                    }),
                ])
            ),
        [items, values, formatValue]
    )

    // Size each column to its widest cell in `ch`, so rows stay aligned even when `renderItem`
    // wraps them in its own element.
    const widths = values.map((v, i) =>
        Math.max(headers[v].length + 2, ...items.map((item) => cells.get(item.key)?.[i].length ?? 0))
    )

    const rows = useMemo(() => {
        if (!sort) {
            return items
        }
        const direction = sort.descending ? -1 : 1
        return [...items].sort((a, b) => {
            if (sort.key === 'label') {
                return a.label.localeCompare(b.label) * direction
            }
            const x = a.values?.[sort.key]
            const y = b.values?.[sort.key]
            // Series without a value sort last in either direction.
            if (x == null || y == null) {
                return x == null ? (y == null ? 0 : 1) : -1
            }
            return (x - y) * direction
        })
    }, [items, sort])

    const hidden = hiddenKeys?.length ? new Set(hiddenKeys) : null
    const header = (key: SortKey, label: string, width?: number): React.ReactElement => {
        const active = sort?.key === key
        return (
            <button
                type="button"
                className={`${width == null ? 'flex-1 min-w-0 text-left' : 'shrink-0 text-right'} cursor-pointer select-none bg-transparent border-0 p-0 font-medium text-(--color-graph-axis-label) whitespace-nowrap`}
                style={width == null ? undefined : { width: `${width}ch` }}
                aria-label={
                    active ? `${label}, sorted ${sort.descending ? 'descending' : 'ascending'}` : `Sort by ${label}`
                }
                data-attr="hog-chart-legend-sort"
                onClick={() =>
                    // Values start highest first and names A to Z, then each click flips the order.
                    setSort((prev) => ({
                        key,
                        descending: prev?.key === key ? !prev.descending : key !== 'label',
                    }))
                }
            >
                {label}
                {active ? (sort.descending ? ' ↓' : ' ↑') : ''}
            </button>
        )
    }

    return (
        <div
            className={`flex flex-col w-full text-xs leading-4 tabular-nums ${className ?? ''}`}
            data-attr={dataAttr}
            data-hog-charts-legend=""
        >
            <div className="flex items-center gap-3 px-1 pb-1">
                {header('label', headers.label)}
                {values.map((v, i) => (
                    <React.Fragment key={v}>{header(v, headers[v], widths[i])}</React.Fragment>
                ))}
            </div>
            {rows.map((item) => {
                const rowClass = `flex w-full min-w-0 items-center gap-3 px-1 py-0.5 rounded text-left${hidden?.has(item.key) ? ' opacity-40' : ''}`
                const inner = (
                    <>
                        <span className="flex flex-1 min-w-0 items-center gap-1.5">
                            <span
                                aria-hidden="true"
                                className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                                style={{ backgroundColor: item.color }}
                            />
                            <span className="truncate min-w-0" title={item.label} data-attr="hog-chart-legend-label">
                                {item.label}
                            </span>
                            {item.secondaryLabel != null && item.secondaryLabel !== '' && (
                                <span
                                    className="shrink-0 text-(--color-graph-axis-label)"
                                    data-attr="hog-chart-legend-secondary"
                                >
                                    {item.secondaryLabel}
                                </span>
                            )}
                        </span>
                        {cells.get(item.key)?.map((text, i) => (
                            <span
                                key={values[i]}
                                className="shrink-0 text-right whitespace-nowrap"
                                style={{ width: `${widths[i]}ch` }}
                                data-attr="hog-chart-legend-value"
                            >
                                {text}
                            </span>
                        ))}
                    </>
                )
                const node = onItemClick ? (
                    <button
                        type="button"
                        className={`${rowClass} cursor-pointer select-none bg-transparent border-0 hover:bg-current/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
                        onClick={(event) =>
                            onItemClick(item.key, { additive: event.metaKey || event.ctrlKey || event.shiftKey })
                        }
                    >
                        {inner}
                    </button>
                ) : (
                    <div className={rowClass}>{inner}</div>
                )
                return <React.Fragment key={item.key}>{renderItem ? renderItem(node, item) : node}</React.Fragment>
            })}
        </div>
    )
}
