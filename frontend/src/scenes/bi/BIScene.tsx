import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import {
    IconArrowLeft,
    IconBinary,
    IconBrackets,
    IconCalculator,
    IconCalendar,
    IconFilter,
    IconLetter,
    IconList,
    IconPlay,
    IconQuestion,
    IconStack,
} from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonTable, LemonTag, Popover, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { SceneExport } from '../sceneTypes'
import { Scene } from '../sceneTypes'
import { BIAggregation, BIQueryFilter, biLogic, columnAlias, columnKey } from './biLogic'

const COLORS = ['#5375ff', '#ff7a9e', '#2bc4ff', '#f6a700', '#7a49ff']

export function formatFilter(filter: BIQueryFilter): JSX.Element {
    return (
        <LemonTag type="primary" key={columnKey(filter.column)}>
            {columnAlias(filter.column)} {filter.expression}
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
    const {
        filteredTables,
        filteredFields,
        selectedTableObject,
        selectedFields,
        queryResponse,
        filters,
        queryString,
        limit,
        searchTerm,
        databaseLoading,
    } = useValues(biLogic)
    const {
        addColumn,
        addAggregation,
        selectTable,
        removeColumn,
        addFilter,
        removeFilter,
        setSearchTerm,
        setLimit,
        setSort,
        refreshQuery,
        resetSelection,
    } = useActions(biLogic)

    const [openColumnPopover, setOpenColumnPopover] = useState<string | null>(null)
    const [openFilterPopover, setOpenFilterPopover] = useState<number | null>(null)

    const rows = useMemo(() => {
        if (!queryResponse?.results) {
            return []
        }

        const headers = queryResponse.columns as { name: string }[] | undefined
        return queryResponse.results.map((row: any[]) => {
            const asObject: Record<string, any> = {}
            row.forEach((value, index) => {
                const name = headers?.[index]?.name || selectedFields[index]?.alias || `col_${index}`
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

    const closePopovers = (): void => {
        setOpenColumnPopover(null)
        setOpenFilterPopover(null)
    }

    return (
        <div className="flex flex-col gap-4 h-full" onClick={closePopovers}>
            <div className="flex gap-4 h-full min-h-0">
                <LemonCard className="flex-1 max-w-80 h-full min-h-0" hoverEffect={false}>
                    <div className="flex items-center gap-2">
                        {selectedTableObject && (
                            <LemonButton type="tertiary" icon={<IconArrowLeft />} onClick={() => resetSelection()} />
                        )}
                        <LemonInput
                            type="search"
                            placeholder={selectedTableObject ? 'Search columns' : 'Search tables'}
                            onChange={(value) => setSearchTerm(value)}
                            value={searchTerm}
                            fullWidth
                        />
                    </div>
                    <div className="mt-2 space-y-1 overflow-y-auto" style={{ maxHeight: 'calc(100% - 60px)' }}>
                        {selectedTableObject ? (
                            <>
                                <div className="font-semibold px-1">{selectedTableObject.name}</div>
                                {filteredFields.length > 0 ? (
                                    <div className="space-y-1">
                                        {filteredFields.map((field) => (
                                            <LemonButton
                                                key={field.name}
                                                size="small"
                                                fullWidth
                                                onClick={() =>
                                                    addColumn({ table: selectedTableObject.name, field: field.name })
                                                }
                                                icon={fieldTypeIcon(field)}
                                            >
                                                {field.name}
                                            </LemonButton>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-muted">No columns match your search.</div>
                                )}
                            </>
                        ) : filteredTables.length > 0 ? (
                            filteredTables.map((table) => (
                                <LemonButton
                                    key={table.name}
                                    icon={<IconStack />}
                                    fullWidth
                                    status={selectedTableObject?.name === table.name ? 'primary' : 'default'}
                                    onClick={() => selectTable(table.name)}
                                >
                                    {table.name}
                                </LemonButton>
                            ))
                        ) : databaseLoading ? (
                            <div className="flex items-center gap-2 text-muted">
                                <Spinner />
                                Loading tables…
                            </div>
                        ) : (
                            <div className="text-muted">No tables match your search.</div>
                        )}
                    </div>
                </LemonCard>

                <div className="flex-1 flex flex-col gap-2 min-h-0">
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
                            {filters.map((filter, index) => (
                                <Popover
                                    key={`${columnKey(filter.column)}-${index}`}
                                    visible={openFilterPopover === index}
                                    onVisibilityChange={(visible) => {
                                        setOpenColumnPopover(null)
                                        setOpenFilterPopover(visible ? index : null)
                                    }}
                                    overlay={
                                        <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => {
                                                    removeFilter(index)
                                                    setOpenFilterPopover(null)
                                                }}
                                            >
                                                Remove filter
                                            </LemonButton>
                                        </div>
                                    }
                                >
                                    <div onClick={(event) => event.stopPropagation()}>{formatFilter(filter)}</div>
                                </Popover>
                            ))}
                        </div>
                    </div>

                    {queryString && (
                        <LemonCard hoverEffect={false}>
                            <div className="text-muted">Generated HogQL</div>
                            <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{queryString}</pre>
                        </LemonCard>
                    )}

                    {numericColumns.length > 0 && (
                        <LemonCard hoverEffect={false}>
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

                    <LemonCard className="flex-1 min-h-0" hoverEffect={false}>
                        {selectedFields.length === 0 ? (
                            <div className="text-muted">Select a table from the left to start the analysis.</div>
                        ) : (
                            <div className="max-h-[60vh] overflow-auto">
                                <LemonTable
                                    dataSource={rows}
                                    loading={!queryResponse && selectedFields.length > 0}
                                    columns={selectedFields.map(({ column, field, alias }) => ({
                                        title: (
                                            <ColumnHeader
                                                alias={alias}
                                                field={field}
                                                onRemove={() => removeColumn(column)}
                                                onAddFilter={(expression) =>
                                                    addFilter({ column, expression: expression || '= ""' })
                                                }
                                                onSort={() => setSort(column)}
                                                onAddAggregation={(aggregation) => addAggregation(column, aggregation)}
                                                isPopoverOpen={openColumnPopover === columnKey(column)}
                                                onPopoverVisibilityChange={(visible) => {
                                                    setOpenFilterPopover(null)
                                                    setOpenColumnPopover(visible ? columnKey(column) : null)
                                                }}
                                            />
                                        ),
                                        dataIndex: alias,
                                        key: columnKey(column),
                                        render: function RenderCell(value) {
                                            if (typeof value === 'number') {
                                                return humanFriendlyNumber(value)
                                            }
                                            return value === null || value === undefined ? '—' : String(value)
                                        },
                                    }))}
                                />
                            </div>
                        )}
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}

function ColumnHeader({
    field,
    alias,
    onRemove,
    onAddFilter,
    onSort,
    onAddAggregation,
    isPopoverOpen,
    onPopoverVisibilityChange,
}: {
    field?: DatabaseSchemaField
    alias: string
    onRemove: () => void
    onAddFilter: (expression?: string) => void
    onSort: () => void
    onAddAggregation: (aggregation: BIAggregation) => void
    isPopoverOpen: boolean
    onPopoverVisibilityChange: (visible: boolean) => void
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const isNumeric = isNumericField(field)

    return (
        <div className="flex items-center gap-1">
            <span className="font-semibold">{alias}</span>
            <Popover
                visible={isPopoverOpen}
                onVisibilityChange={onPopoverVisibilityChange}
                overlay={
                    <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                        <LemonInput
                            placeholder="= 'value' or > 10"
                            value={draft}
                            onChange={setDraft}
                            onPressEnter={() => {
                                onAddFilter(draft)
                                setDraft('')
                                onPopoverVisibilityChange(false)
                            }}
                        />
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onAddFilter(draft)
                                setDraft('')
                                onPopoverVisibilityChange(false)
                            }}
                            icon={<IconFilter />}
                        >
                            Add filter
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onAddAggregation('count')
                                onPopoverVisibilityChange(false)
                            }}
                        >
                            Count
                        </LemonButton>
                        {isNumeric && (
                            <div className="grid grid-cols-3 gap-1">
                                {(['min', 'max', 'sum'] as BIAggregation[]).map((aggregation) => (
                                    <LemonButton
                                        key={aggregation}
                                        type="secondary"
                                        onClick={() => {
                                            onAddAggregation(aggregation)
                                            onPopoverVisibilityChange(false)
                                        }}
                                    >
                                        {aggregation.toUpperCase()}
                                    </LemonButton>
                                ))}
                            </div>
                        )}
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onSort()
                                onPopoverVisibilityChange(false)
                            }}
                        >
                            Sort
                        </LemonButton>
                        <LemonButton
                            status="danger"
                            onClick={() => {
                                onRemove()
                                onPopoverVisibilityChange(false)
                            }}
                        >
                            Remove column
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconFilter />}
                    aria-label="Column options"
                    onClick={(event) => {
                        event.stopPropagation()
                        onPopoverVisibilityChange(!isPopoverOpen)
                    }}
                />
            </Popover>
        </div>
    )
}

function isNumericField(field?: DatabaseSchemaField): boolean {
    if (!field?.type || typeof field.type !== 'string') {
        return false
    }
    const type = field.type.toLowerCase()
    return type.includes('int') || type.includes('float') || type.includes('decimal') || type.includes('double')
}

function fieldTypeIcon(field?: DatabaseSchemaField): JSX.Element {
    if (!field?.type || typeof field.type !== 'string') {
        return <IconQuestion />
    }

    const type = field.type.toLowerCase()

    if (isNumericField(field) || type.includes('decimal') || type.includes('number')) {
        return <IconCalculator />
    }

    if (type.includes('date') || type.includes('time')) {
        return <IconCalendar />
    }

    if (type.includes('bool')) {
        return <IconBinary />
    }

    if (type.includes('array')) {
        return <IconList />
    }

    if (type.includes('json') || type.includes('map') || type.includes('struct')) {
        return <IconBrackets />
    }

    return <IconLetter />
}
