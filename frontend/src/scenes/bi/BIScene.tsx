import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconFilter, IconPlay, IconPlus, IconStack } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonTable, LemonTag, Popover } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { SceneExport } from '../sceneTypes'
import { Scene } from '../sceneTypes'
import { BIQueryColumn, BIQueryFilter, biLogic, columnKey } from './biLogic'

const COLORS = ['#5375ff', '#ff7a9e', '#2bc4ff', '#f6a700', '#7a49ff']

export function formatFilter(filter: BIQueryFilter): JSX.Element {
    return (
        <LemonTag type="primary" key={columnKey(filter.column)}>
            {columnKey(filter.column)} {filter.expression}
        </LemonTag>
    )
}

function MiniPie({ values }: { values: number[] }): JSX.Element {
    const total = values.reduce((acc, cur) => acc + cur, 0)
    const normalized = values.map((value) => (total ? value / total : 0))
    const gradient = normalized
        .map((value, index) => {
            const start = normalized.slice(0, index).reduce((acc, cur) => acc + cur, 0)
            const end = start + value
            return `${COLORS[index % COLORS.length]} ${start * 100}% ${end * 100}%`
        })
        .join(', ')

    return <div className="h-12 w-12 rounded-full" style={{ background: `conic-gradient(${gradient})` }} />
}

function MiniLine({ values }: { values: number[] }): JSX.Element {
    const maxValue = Math.max(...values, 1)
    const points = values.map((value, index) => `${index},${Math.max(0, 100 - (value / maxValue) * 100)}`).join(' ')
    return (
        <svg viewBox="0 0 10 100" className="h-12 w-full text-primary">
            <polyline fill="none" stroke="currentColor" strokeWidth="1" points={points} />
        </svg>
    )
}

export const scene: SceneExport = {
    component: BIScene,
    logic: biLogic,
    scene: Scene.BI,
}

export function BIScene(): JSX.Element {
    const { filteredTables } = useValues(databaseTableListLogic)
    const { selectedTableObject, selectedFields, queryResponse, filters, queryString, limit } = useValues(biLogic)
    const {
        addColumn,
        selectTable,
        removeColumn,
        addFilter,
        removeFilter,
        setSearchTerm,
        setLimit,
        setSort,
        refreshQuery,
    } = useActions(biLogic)

    const rows = useMemo(() => {
        if (!queryResponse?.results) {
            return []
        }

        const headers = queryResponse.columns as { name: string }[] | undefined
        return queryResponse.results.map((row: any[]) => {
            const asObject: Record<string, any> = {}
            row.forEach((value, index) => {
                const name = headers?.[index]?.name || selectedFields[index]?.column.field || `col_${index}`
                asObject[name] = value
            })
            return asObject
        })
    }, [queryResponse, selectedFields])

    const numericColumns = useMemo(() => {
        if (rows.length === 0) {
            return []
        }
        const keys = Object.keys(rows[0] || {})
        return keys.filter((key) => rows.some((row) => typeof row[key] === 'number'))
    }, [rows])

    const timeColumns = useMemo(() => {
        if (rows.length === 0) {
            return []
        }
        const keys = Object.keys(rows[0] || {})
        return keys.filter((key) => {
            const value = rows[0]?.[key]
            return typeof value === 'string' && /\d{4}-\d{2}-\d{2}/.test(value)
        })
    }, [rows])

    const chartValues = numericColumns.length > 0 ? rows.map((row) => Number(row[numericColumns[0]])) : []

    return (
        <div className="flex flex-col gap-4 h-full">
            <div className="flex gap-4 h-full">
                <LemonCard className="flex-1 max-w-80 h-full">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search tables or fields"
                            onChange={(value) => setSearchTerm(value)}
                            fullWidth
                        />
                    </div>
                    <div className="mt-2 space-y-1 overflow-y-auto" style={{ maxHeight: 'calc(100% - 60px)' }}>
                        {filteredTables.map((table) => (
                            <div key={table.name}>
                                <div className="flex items-center justify-between gap-2">
                                    <LemonButton
                                        icon={<IconStack />}
                                        fullWidth
                                        status={selectedTableObject?.name === table.name ? 'primary' : 'default'}
                                        onClick={() => selectTable(table.name)}
                                    >
                                        {table.name}
                                    </LemonButton>
                                </div>
                                {selectedTableObject?.name === table.name && (
                                    <div className="mt-1 grid grid-cols-2 gap-1">
                                        {Object.values(table.fields).map((field) => (
                                            <LemonButton
                                                key={field.name}
                                                size="small"
                                                fullWidth
                                                onClick={() => addColumn({ table: table.name, field: field.name })}
                                                icon={<IconPlus />}
                                            >
                                                {field.name}
                                            </LemonButton>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </LemonCard>

                <div className="flex-1 space-y-2">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <LemonButton type="secondary" onClick={() => refreshQuery()} icon={<IconPlay />}>
                                Run query
                            </LemonButton>
                            <LemonInput
                                type="number"
                                min={1}
                                value={limit}
                                onChange={(value) => setLimit(Number(value) || 50)}
                                suffix="rows"
                                style={{ width: 140 }}
                            />
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {filters.map((filter) => (
                                <Popover
                                    key={columnKey(filter.column)}
                                    overlay={
                                        <div className="space-y-2">
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => removeFilter(filter.column)}
                                            >
                                                Remove filter
                                            </LemonButton>
                                        </div>
                                    }
                                >
                                    {formatFilter(filter)}
                                </Popover>
                            ))}
                        </div>
                    </div>

                    {numericColumns.length > 0 && (
                        <LemonCard>
                            <div className="flex items-center gap-4">
                                <MiniPie values={chartValues} />
                                <div className="space-y-1">
                                    <div className="text-muted">Pie of {numericColumns[0]}</div>
                                    <div className="text-2xl font-semibold">
                                        {humanFriendlyNumber(chartValues.reduce((acc, cur) => acc + cur, 0))}
                                    </div>
                                </div>
                                {timeColumns.length > 0 && <MiniLine values={chartValues.slice(0, 20)} />}
                            </div>
                        </LemonCard>
                    )}

                    <LemonCard>
                        {selectedFields.length === 0 ? (
                            <div className="text-muted">Select columns from the left to build your table.</div>
                        ) : (
                            <LemonTable
                                dataSource={rows}
                                loading={!queryResponse && selectedFields.length > 0}
                                columns={selectedFields.map(({ column }) => ({
                                    title: (
                                        <ColumnHeader
                                            column={column}
                                            onRemove={() => removeColumn(column)}
                                            onAddFilter={(expression) =>
                                                addFilter({ column, expression: expression || '= ""' })
                                            }
                                            onSort={() => setSort(column)}
                                        />
                                    ),
                                    dataIndex: column.field,
                                    key: columnKey(column),
                                    render: function RenderCell(value) {
                                        if (typeof value === 'number') {
                                            return humanFriendlyNumber(value)
                                        }
                                        return value === null || value === undefined ? '—' : String(value)
                                    },
                                }))}
                            />
                        )}
                    </LemonCard>

                    {queryString && (
                        <LemonCard>
                            <div className="text-muted">Generated HogQL</div>
                            <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{queryString}</pre>
                        </LemonCard>
                    )}
                </div>
            </div>
        </div>
    )
}

function ColumnHeader({
    column,
    onRemove,
    onAddFilter,
    onSort,
}: {
    column: BIQueryColumn
    onRemove: () => void
    onAddFilter: (expression?: string) => void
    onSort: () => void
}): JSX.Element {
    const [draft, setDraft] = useState('')

    return (
        <div className="flex items-center gap-1">
            <span className="font-semibold">{column.field}</span>
            <Popover
                overlay={
                    <div className="space-y-2">
                        <LemonInput
                            placeholder="= 'value' or > 10"
                            value={draft}
                            onChange={setDraft}
                            onPressEnter={() => onAddFilter(draft)}
                        />
                        <LemonButton type="secondary" onClick={() => onAddFilter(draft)} icon={<IconFilter />}>
                            Add filter
                        </LemonButton>
                        <LemonButton type="secondary" onClick={() => onSort()}>
                            Sort
                        </LemonButton>
                        <LemonButton status="danger" onClick={onRemove}>
                            Remove column
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton size="small" type="secondary" icon={<IconFilter />}>
                    Options
                </LemonButton>
            </Popover>
        </div>
    )
}
