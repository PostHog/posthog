import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconArrowLeft,
    IconBinary,
    IconBrackets,
    IconCalculator,
    IconCalendar,
    IconExpand45,
    IconFilter,
    IconLetter,
    IconList,
    IconPlay,
    IconQuestion,
    IconStack,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonTable,
    LemonTag,
    LemonTextArea,
    Popover,
    Spinner,
} from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { SceneExport } from '../sceneTypes'
import { Scene } from '../sceneTypes'
import { urls } from '../urls'
import {
    BIAggregation,
    BIQueryFilter,
    BISortDirection,
    BITimeAggregation,
    FieldTreeNode,
    biLogic,
    columnAlias,
    columnKey,
    isJsonField,
} from './biLogic'

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

function FieldTree({
    nodes,
    expandedFields,
    onToggle,
    onSelect,
    depth = 0,
}: {
    nodes: FieldTreeNode[]
    expandedFields: Set<string>
    onToggle: (path: string) => void
    onSelect: (path: string) => void
    depth?: number
}): JSX.Element {
    const [openJsonPopover, setOpenJsonPopover] = useState<string | null>(null)
    const [jsonPathDraft, setJsonPathDraft] = useState('')
    const jsonTextAreaRef = useRef<HTMLTextAreaElement | null>(null)

    const focusJsonTextArea = (): void => {
        requestAnimationFrame(() => {
            const textArea = jsonTextAreaRef.current
            if (textArea) {
                const length = textArea.value.length
                textArea.focus()
                textArea.setSelectionRange(length, length)
                textArea.scrollTop = textArea.scrollHeight
            }
        })
    }

    const closeJsonPopover = (): void => {
        setOpenJsonPopover(null)
        setJsonPathDraft('')
    }

    useEffect(() => {
        if (openJsonPopover) {
            focusJsonTextArea()
        }
    }, [openJsonPopover])

    return (
        <div className="flex flex-col">
            {nodes.map((node) => {
                const hasChildren = node.children.length > 0
                const isExpanded = expandedFields.has(node.path)
                const isJson = isJsonField(node.field)

                const handleJsonSubmit = (path: string): void => {
                    const selectedPath = jsonPathDraft.trim() || path
                    onSelect(selectedPath)
                    setJsonPathDraft('')
                    setOpenJsonPopover(null)
                }

                const handleClick = (): void => {
                    if (isJson) {
                        setOpenJsonPopover(node.path)
                        setJsonPathDraft(node.path)
                    } else if (hasChildren) {
                        onToggle(node.path)
                    } else {
                        onSelect(node.path)
                    }
                }

                return (
                    <div key={node.path}>
                        <div className="flex items-center gap-2">
                            {isJson ? (
                                <Popover
                                    visible={openJsonPopover === node.path}
                                    onVisibilityChange={(visible) => {
                                        setOpenJsonPopover(visible ? node.path : null)
                                        setJsonPathDraft(visible ? node.path : '')
                                        if (visible) {
                                            focusJsonTextArea()
                                        }
                                    }}
                                    onClickOutside={closeJsonPopover}
                                    overlay={
                                        <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                                            <div className="text-muted">Add column or nested field</div>
                                            <div className="text-muted">e.g. properties.$browser</div>
                                            <LemonTextArea
                                                ref={jsonTextAreaRef}
                                                value={jsonPathDraft}
                                                minRows={1}
                                                onChange={(value) => setJsonPathDraft((value || '').trim())}
                                                onFocus={focusJsonTextArea}
                                                autoFocus
                                                onKeyDown={(event) => {
                                                    if (event.key === 'Enter' && !event.shiftKey) {
                                                        event.preventDefault()
                                                        handleJsonSubmit(node.path)
                                                    }
                                                }}
                                            />
                                            <LemonButton
                                                type="primary"
                                                onClick={(event) => {
                                                    event.stopPropagation()
                                                    handleJsonSubmit(node.path)
                                                }}
                                                fullWidth
                                            >
                                                Add column
                                            </LemonButton>
                                        </div>
                                    }
                                >
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        className="justify-start"
                                        icon={
                                            hasChildren ? (
                                                <span className="text-muted">{isExpanded ? '▾' : '▸'}</span>
                                            ) : (
                                                fieldTypeIcon(node.field)
                                            )
                                        }
                                        onClick={() => handleClick()}
                                        style={{ paddingLeft: depth * 12 }}
                                    >
                                        {node.field.name}
                                    </LemonButton>
                                </Popover>
                            ) : (
                                <LemonButton
                                    size="small"
                                    fullWidth
                                    className="justify-start"
                                    icon={
                                        hasChildren ? (
                                            <span className="text-muted">{isExpanded ? '▾' : '▸'}</span>
                                        ) : (
                                            fieldTypeIcon(node.field)
                                        )
                                    }
                                    onClick={() => handleClick()}
                                    style={{ paddingLeft: depth * 12 }}
                                >
                                    {node.field.name}
                                </LemonButton>
                            )}
                        </div>
                        {hasChildren && isExpanded && (
                            <div className="ml-2">
                                <FieldTree
                                    nodes={node.children}
                                    expandedFields={expandedFields}
                                    onToggle={onToggle}
                                    onSelect={onSelect}
                                    depth={depth + 1}
                                />
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
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
        selectedFieldTrees,
        selectedTableObject,
        selectedFields,
        queryResponse,
        queryResponseLoading,
        filters,
        queryString,
        _queryString,
        limit,
        searchTerm,
        databaseLoading,
        sort,
    } = useValues(biLogic)
    const {
        addColumn,
        setColumnAggregation,
        setColumnTimeInterval,
        selectTable,
        removeColumn,
        addFilter,
        updateFilter,
        removeFilter,
        setTableSearchTerm,
        setColumnSearchTerm,
        setLimit,
        setSort,
        refreshQuery,
        resetSelection,
    } = useActions(biLogic)

    const [openColumnPopover, setOpenColumnPopover] = useState<string | null>(null)
    const [openFilterPopover, setOpenFilterPopover] = useState<number | null>(null)
    const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set())

    useEffect(() => {
        setExpandedFields(new Set())
    }, [selectedTableObject?.name])

    const rows = useMemo(() => {
        if (!queryResponse?.results || selectedFields.length === 0 || queryResponseLoading) {
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
    }, [queryResponse, selectedFields, queryResponseLoading])

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
                            onChange={(value) =>
                                selectedTableObject ? setColumnSearchTerm(value) : setTableSearchTerm(value)
                            }
                            value={searchTerm}
                            fullWidth
                        />
                    </div>
                    <div className="mt-2 overflow-y-auto" style={{ maxHeight: 'calc(100% - 60px)' }}>
                        {selectedTableObject ? (
                            <>
                                <div className="font-semibold px-1">{selectedTableObject.name}</div>
                                {selectedTableObject?.source?.source_type === 'Postgres' ? (
                                    <div className="text-xs text-muted px-1">via postgres direct connection</div>
                                ) : (
                                    <div className="text-xs text-muted px-1">via posthog data warehouse</div>
                                )}
                                {selectedFieldTrees.length > 0 ? (
                                    <FieldTree
                                        nodes={selectedFieldTrees}
                                        expandedFields={expandedFields}
                                        onToggle={(path) =>
                                            setExpandedFields((current) => {
                                                const next = new Set(current)
                                                if (next.has(path)) {
                                                    next.delete(path)
                                                } else {
                                                    next.add(path)
                                                }
                                                return next
                                            })
                                        }
                                        onSelect={(path) => addColumn({ table: selectedTableObject.name, field: path })}
                                    />
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
                                <FilterPill
                                    key={`${columnKey(filter.column)}-${index}`}
                                    filter={filter}
                                    isOpen={openFilterPopover === index}
                                    onOpenChange={(visible) => {
                                        setOpenColumnPopover(null)
                                        setOpenFilterPopover(visible ? index : null)
                                    }}
                                    onUpdate={(expression) => updateFilter(index, expression)}
                                    onRemove={() => removeFilter(index)}
                                />
                            ))}
                        </div>
                    </div>

                    {_queryString && (
                        <LemonCard hoverEffect={false}>
                            <div className="flex items-start justify-between gap-2">
                                <div className="text-muted">Generated HogQL</div>
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    icon={<IconExpand45 />}
                                    onClick={() => newInternalTab(urls.sqlEditor(_queryString))}
                                    tooltip="Open in SQL editor"
                                />
                            </div>
                            <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{queryString}</pre>
                        </LemonCard>
                    )}

                    {numericColumns.length > 0 && selectedFields.length > 0 && !queryResponseLoading && (
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

                    <LemonCard className="flex-1 min-h-0 flex flex-col min-w-full max-w-full" hoverEffect={false}>
                        {selectedFields.length === 0 ? (
                            <div className="text-muted">Select a table from the left to start the analysis.</div>
                        ) : (
                            <div className="flex-1 min-h-0 overflow-auto max-w-full">
                                <LemonTable
                                    dataSource={rows}
                                    loading={queryResponseLoading && selectedFields.length > 0}
                                    columns={selectedFields.map(({ column, field, alias }) => ({
                                        title: (
                                            <ColumnHeader
                                                column={column}
                                                alias={alias}
                                                field={field}
                                                onRemove={() => removeColumn(column)}
                                                onAddFilter={(expression) =>
                                                    addFilter({ column, expression: expression || '= ""' })
                                                }
                                                sortDirection={
                                                    sort && columnKey(sort.column) === columnKey(column)
                                                        ? sort.direction
                                                        : null
                                                }
                                                onSort={(direction) => setSort(column, direction)}
                                                onSetAggregation={(aggregation) =>
                                                    setColumnAggregation(
                                                        column,
                                                        aggregation === column.aggregation ? null : aggregation
                                                    )
                                                }
                                                onSetTimeInterval={(timeInterval) =>
                                                    setColumnTimeInterval(
                                                        column,
                                                        timeInterval === column.timeInterval ? null : timeInterval
                                                    )
                                                }
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
    column,
    field,
    alias,
    sortDirection,
    onRemove,
    onAddFilter,
    onSort,
    onSetAggregation,
    onSetTimeInterval,
    isPopoverOpen,
    onPopoverVisibilityChange,
}: {
    column: BIQueryColumn
    field?: DatabaseSchemaField
    alias: string
    sortDirection: BISortDirection | null
    onRemove: () => void
    onAddFilter: (expression?: string) => void
    onSort: (direction: BISortDirection | null) => void
    onSetAggregation: (aggregation?: BIAggregation | null) => void
    onSetTimeInterval: (timeInterval?: BITimeAggregation | null) => void
    isPopoverOpen: boolean
    onPopoverVisibilityChange: (visible: boolean) => void
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const isTemporal = isTemporalField(field)
    const isNumeric = isNumericField(field)
    const availableAggregations: BIAggregation[] = isNumeric ? ['count', 'min', 'max', 'sum'] : ['count', 'min', 'max']

    return (
        <div className="flex items-center gap-1">
            <span className="font-semibold">{alias}</span>
            <Popover
                visible={isPopoverOpen}
                onVisibilityChange={onPopoverVisibilityChange}
                overlay={
                    <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                        <LemonButton
                            status="danger"
                            size="small"
                            onClick={() => {
                                onRemove()
                                onPopoverVisibilityChange(false)
                            }}
                        >
                            Remove column
                        </LemonButton>
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
                            size="small"
                            onClick={() => {
                                onAddFilter(draft)
                                setDraft('')
                                onPopoverVisibilityChange(false)
                            }}
                            icon={<IconFilter />}
                        >
                            Add filter
                        </LemonButton>
                        <div className="space-y-1">
                            <div className="text-muted">Aggregation</div>
                            <div className="grid grid-cols-4 gap-1">
                                <LemonButton
                                    type={!column.aggregation ? 'primary' : 'secondary'}
                                    size="small"
                                    active={!column.aggregation}
                                    status={!column.aggregation ? 'primary' : 'default'}
                                    onClick={() => {
                                        onSetAggregation(null)
                                        onPopoverVisibilityChange(false)
                                    }}
                                >
                                    None
                                </LemonButton>
                                {availableAggregations.map((aggregation) => (
                                    <LemonButton
                                        key={aggregation}
                                        type={column.aggregation === aggregation ? 'primary' : 'secondary'}
                                        size="small"
                                        status={column.aggregation === aggregation ? 'primary' : 'default'}
                                        active={column.aggregation === aggregation}
                                        onClick={() => {
                                            onSetAggregation(aggregation)
                                            onPopoverVisibilityChange(false)
                                        }}
                                    >
                                        {aggregation.toUpperCase()}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                        {isTemporal && (
                            <div className="space-y-1">
                                <div className="text-muted">Date aggregation</div>
                                <div className="grid grid-cols-4 gap-1">
                                    {[null, 'hour', 'day', 'week', 'month'].map((interval) => (
                                        <LemonButton
                                            key={interval || 'none'}
                                            type="secondary"
                                            size="small"
                                            status={column.timeInterval === interval ? 'primary' : 'default'}
                                            active={column.timeInterval === interval}
                                            onClick={() => {
                                                onSetTimeInterval(interval as BITimeAggregation | null)
                                                onPopoverVisibilityChange(false)
                                            }}
                                        >
                                            {(interval || 'none').toString().replace(/^./, (c) => c.toUpperCase())}
                                        </LemonButton>
                                    ))}
                                </div>
                            </div>
                        )}
                        <div className="grid grid-cols-2 gap-1">
                            {(['asc', 'desc'] as BISortDirection[]).map((direction) => (
                                <LemonButton
                                    key={direction}
                                    type="secondary"
                                    size="small"
                                    status={sortDirection === direction ? 'primary' : 'default'}
                                    active={sortDirection === direction}
                                    onClick={() => {
                                        onSort(sortDirection === direction ? null : direction)
                                        onPopoverVisibilityChange(false)
                                    }}
                                >
                                    Sort {direction}
                                </LemonButton>
                            ))}
                        </div>
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

function isTemporalField(field?: DatabaseSchemaField): boolean {
    if (!field?.type || typeof field.type !== 'string') {
        return false
    }
    const type = field.type.toLowerCase()
    return type.includes('date') || type.includes('time')
}

function FilterPill({
    filter,
    isOpen,
    onOpenChange,
    onUpdate,
    onRemove,
}: {
    filter: BIQueryFilter
    isOpen: boolean
    onOpenChange: (visible: boolean) => void
    onUpdate: (expression: string) => void
    onRemove: () => void
}): JSX.Element {
    const [draft, setDraft] = useState(filter.expression)

    useEffect(() => {
        setDraft(filter.expression)
    }, [filter.expression])

    return (
        <Popover
            visible={isOpen}
            onVisibilityChange={onOpenChange}
            overlay={
                <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                    <LemonInput
                        placeholder="= 'value' or > 10"
                        value={draft}
                        onChange={setDraft}
                        onPressEnter={() => {
                            onUpdate(draft)
                            onOpenChange(false)
                        }}
                    />
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onUpdate(draft)
                                onOpenChange(false)
                            }}
                        >
                            Update filter
                        </LemonButton>
                        <LemonButton
                            status="danger"
                            onClick={() => {
                                onRemove()
                                onOpenChange(false)
                            }}
                        >
                            Remove
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div
                className="cursor-pointer"
                onClick={(event) => {
                    event.stopPropagation()
                    onOpenChange(!isOpen)
                }}
            >
                {formatFilter(filter)}
            </div>
        </Popover>
    )
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

    if (isJsonField(field)) {
        return <IconBrackets />
    }

    return <IconLetter />
}
