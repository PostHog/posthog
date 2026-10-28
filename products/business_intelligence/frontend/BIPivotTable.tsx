import { useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { ChartSettings } from '~/queries/schema/schema-general'

import { captureBIWorksheetAction } from './biEditorAnalytics'
import { getBIFieldPillLabel } from './biEditorTypes'
import { biPivotCellKey, biPivotKey, BIPivotMember, buildBIPivotModel, visibleBIPivotMembers } from './biPivot'
import { formatBIMeasure, getBIResultMeasures } from './biResultPresentation'

// Virtualization still needs a full-width scroll area, which browsers cap even with only a few cells mounted.
const MAX_PIVOT_MEASURE_COLUMNS = 10000

export function BIPivotTable({
    config,
    columns,
    results,
    chartSettings,
    onInspect,
    embedded,
}: {
    embedded?: boolean
    config: BIConfig
    columns: string[]
    results: unknown[][]
    chartSettings?: ChartSettings
    onInspect?: (record: Record<string, unknown>) => void
}): JSX.Element {
    const [collapsedRows, setCollapsedRows] = useState<Set<string>>(new Set())
    const [collapsedColumns, setCollapsedColumns] = useState<Set<string>>(new Set())
    const model = useMemo(() => buildBIPivotModel(config, columns, results), [config, columns, results])
    const columnMembers = useMemo(
        () => new Map(visibleBIPivotMembers(model.columns, new Set(), true).map((member) => [member.key, member])),
        [model.columns]
    )
    const measures = getBIResultMeasures(config, chartSettings)
    const rows = useMemo(() => visibleBIPivotMembers(model.rows, collapsedRows, true), [model.rows, collapsedRows])
    const visibleColumns = visibleBIPivotMembers(model.columns, collapsedColumns, !!config.totals?.subtotals)
    if (visibleColumns.length * measures.length > MAX_PIVOT_MEASURE_COLUMNS) {
        return (
            <LemonBanner type="info">
                This pivot has more than 10,000 measure columns. Reduce the column dimensions or use Top N.
            </LemonBanner>
        )
    }
    const toggle = (member: BIPivotMember, side: 'rows' | 'columns'): void => {
        const setter = side === 'rows' ? setCollapsedRows : setCollapsedColumns
        setter((current) => {
            const next = new Set(current)
            next.has(member.key) ? next.delete(member.key) : next.add(member.key)
            return next
        })
        captureBIWorksheetAction('pivot_hierarchy_toggled', config, {
            hierarchy_axis: side,
            hierarchy_depth: member.path.length,
            expanded: (side === 'rows' ? collapsedRows : collapsedColumns).has(member.key),
        })
    }
    const header = (member: BIPivotMember, side: 'rows' | 'columns'): JSX.Element => {
        const collapsed = (side === 'rows' ? collapsedRows : collapsedColumns).has(member.key)
        return member.children.length ? (
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={collapsed ? <IconChevronRight /> : <IconChevronDown />}
                aria-expanded={!collapsed}
                aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${member.label}`}
                data-attr={`bi-pivot-toggle-${side}`}
                onClick={() => toggle(member, side)}
            >
                {member.label}
            </LemonButton>
        ) : (
            <span>{member.label}</span>
        )
    }
    const headerRows = Array.from({ length: config.columns.length }, (_, depth) => {
        const cells: { title: React.ReactNode; colSpan: number; key: string }[] = [
            {
                title: depth === 0 ? config.columns.map(getBIFieldPillLabel).join(' / ') : '',
                colSpan: 1,
                key: 'rows',
            },
        ]
        for (const column of visibleColumns) {
            const path = column.path.slice(0, depth + 1)
            const key = biPivotKey(path)
            const previous = cells[cells.length - 1]
            if (previous.key === key) {
                previous.colSpan += measures.length
            } else {
                const member = columnMembers.get(key)
                cells.push({
                    key,
                    colSpan: measures.length,
                    title:
                        depth < column.path.length && member
                            ? header(member, 'columns')
                            : depth === 0 && !column.path.length
                              ? 'Total'
                              : depth === column.path.length && column.children.length
                                ? 'Subtotal'
                                : '',
                })
            }
        }
        return cells
    })
    return (
        <div className="h-full w-full min-h-0 min-w-0 flex" data-attr="bi-pivot-table">
            <LemonTable<BIPivotMember>
                className="DataVisualizationTable"
                embedded={embedded}
                allowContentScroll
                virtualized
                virtualizedColumnWidth={visibleColumns.length * measures.length > 50 ? 192 : undefined}
                rowKey="key"
                dataSource={rows}
                useURLForSorting={false}
                firstColumnSticky
                uppercaseHeader={false}
                headerRows={headerRows}
                emptyState="No results for these filters"
                columns={[
                    {
                        key: 'rows',
                        title: config.rows.map(getBIFieldPillLabel).join(' / '),
                        render: (_, member) => (
                            <div className="flex items-center gap-1 whitespace-nowrap">
                                {member.path.slice(1).map((_, index) => (
                                    <span key={index} className="w-3 shrink-0" />
                                ))}
                                {header(member, 'rows')}
                            </div>
                        ),
                    },
                    ...visibleColumns.flatMap((column) =>
                        measures.map((measure) => ({
                            key: `${column.key}:${measure.column}`,
                            title: measure.label,
                            align: 'right' as const,
                            render: (_: unknown, row: BIPivotMember) => {
                                const record = model.cells.get(biPivotCellKey(row.path, column.path))
                                const showValue =
                                    !row.children.length || collapsedRows.has(row.key) || config.totals?.subtotals
                                const label = formatBIMeasure(
                                    showValue ? record?.[measure.column] : null,
                                    measure.settings
                                )
                                return record && showValue && onInspect ? (
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        fullWidth
                                        noPadding
                                        data-attr="bi-pivot-inspect"
                                        onClick={() => onInspect(record)}
                                        tooltip="Explore this result"
                                    >
                                        <span className="w-full text-right">{label}</span>
                                    </LemonButton>
                                ) : (
                                    label
                                )
                            },
                        }))
                    ),
                ]}
            />
        </div>
    )
}
