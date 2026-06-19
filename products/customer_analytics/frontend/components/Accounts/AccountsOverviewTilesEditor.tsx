import { DndContext } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { AccountColumnOption } from './accountsColumnConfigLogic'
import {
    accountsOverviewTilesLogic,
    AccountsOverviewTile,
    AccountsOverviewTileMetric,
    AccountsOverviewTileMetricType,
} from './accountsOverviewTilesLogic'
import {
    ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS,
    AccountsOverviewThresholdOperator,
    MAX_ACCOUNTS_OVERVIEW_TILES,
} from './constants'

const METRIC_TYPE_LABELS: Record<AccountsOverviewTileMetricType, string> = {
    count: 'Count of accounts',
    sum: 'Sum of column',
    avg: 'Average of column',
    count_threshold: 'Count above/below threshold',
}

function fallbackColumn(options: AccountColumnOption[]): AccountColumnOption | null {
    return options[0] ?? null
}

function defaultLabelForMetric(metric: AccountsOverviewTileMetric): string {
    switch (metric.type) {
        case 'count':
            return 'Accounts'
        case 'sum':
            return `Total ${metric.columnLabel}`
        case 'avg':
            return `Average ${metric.columnLabel}`
        case 'count_threshold':
            return `Accounts ${metric.operator} ${metric.value}`
    }
}

function metricOfType(
    type: AccountsOverviewTileMetricType,
    options: AccountColumnOption[],
    previous: AccountsOverviewTileMetric
): AccountsOverviewTileMetric | null {
    if (type === 'count') {
        return { type: 'count' }
    }
    let columnExpression: string
    let columnLabel: string
    if (previous.type !== 'count') {
        columnExpression = previous.columnExpression
        columnLabel = previous.columnLabel
    } else {
        const fallback = fallbackColumn(options)
        if (!fallback) {
            return null
        }
        columnExpression = fallback.expression
        columnLabel = fallback.name
    }
    if (type === 'count_threshold') {
        return {
            type,
            columnExpression,
            columnLabel,
            operator: previous.type === 'count_threshold' ? previous.operator : '>',
            value: previous.type === 'count_threshold' ? previous.value : 0,
        }
    }
    return { type, columnExpression, columnLabel }
}

export function AccountsOverviewTilesEditor({
    isOpen,
    onClose,
}: {
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { tiles, numericColumns } = useValues(accountsOverviewTilesLogic)
    const { addTile, updateTile, removeTile, moveTile, resetTiles } = useActions(accountsOverviewTilesLogic)

    const handleAddTile = (): void => {
        addTile({ label: 'Accounts', metric: { type: 'count' } })
    }

    return (
        <LemonModal
            isOpen={isOpen}
            title="Edit overview tiles"
            onClose={onClose}
            className="w-full max-w-248"
            footer={
                <>
                    <div className="flex-1 flex items-center gap-2">
                        <LemonButton type="secondary" onClick={resetTiles}>
                            Reset to defaults
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={onClose} data-attr="accounts-overview-tiles-close">
                        Close
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                {tiles.length === 0 ? (
                    <div className="text-secondary text-sm">No tiles configured yet — add one to get started.</div>
                ) : (
                    <DndContext
                        onDragEnd={({ active, over }) => {
                            if (!over || active.id === over.id) {
                                return
                            }
                            const oldIndex = tiles.findIndex((t) => t.id === active.id)
                            const newIndex = tiles.findIndex((t) => t.id === over.id)
                            if (oldIndex >= 0 && newIndex >= 0) {
                                moveTile(oldIndex, newIndex)
                            }
                        }}
                        modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                    >
                        <SortableContext items={tiles.map((t) => t.id)} strategy={verticalListSortingStrategy}>
                            <div className="flex flex-col gap-2">
                                {tiles.map((tile) => (
                                    <TileEditorRow
                                        key={tile.id}
                                        tile={tile}
                                        numericColumns={numericColumns}
                                        onChange={(next) => updateTile(tile.id, next)}
                                        onRemove={() => removeTile(tile.id)}
                                    />
                                ))}
                            </div>
                        </SortableContext>
                    </DndContext>
                )}
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={handleAddTile}
                    disabledReason={
                        tiles.length >= MAX_ACCOUNTS_OVERVIEW_TILES
                            ? `You can add up to ${MAX_ACCOUNTS_OVERVIEW_TILES} tiles`
                            : undefined
                    }
                    data-attr="accounts-overview-tiles-add"
                >
                    Add tile
                </LemonButton>
            </div>
        </LemonModal>
    )
}

interface TileEditorRowProps {
    tile: AccountsOverviewTile
    numericColumns: AccountColumnOption[]
    onChange: (next: Omit<AccountsOverviewTile, 'id'>) => void
    onRemove: () => void
}

function TileEditorRow({ tile, numericColumns, onChange, onRemove }: TileEditorRowProps): JSX.Element {
    const { setNodeRef, attributes, transform, transition, listeners } = useSortable({ id: tile.id })
    const needsColumn = tile.metric.type !== 'count'
    const noNumericColumns = numericColumns.length === 0

    const columnOptions = useMemo(
        () => numericColumns.map((column) => ({ value: column.expression, label: column.name })),
        [numericColumns]
    )

    const onMetricTypeChange = (next: AccountsOverviewTileMetricType): void => {
        const nextMetric = metricOfType(next, numericColumns, tile.metric)
        if (!nextMetric) {
            return
        }
        onChange({ label: tile.label, metric: nextMetric })
    }

    const onColumnChange = (expression: string): void => {
        if (tile.metric.type === 'count') {
            return
        }
        const column = numericColumns.find((c) => c.expression === expression)
        if (!column) {
            return
        }
        const previousLabelLooksAuto = tile.label === defaultLabelForMetric(tile.metric)
        const nextMetric: AccountsOverviewTileMetric = {
            ...tile.metric,
            columnExpression: column.expression,
            columnLabel: column.name,
        }
        onChange({
            label: previousLabelLooksAuto ? defaultLabelForMetric(nextMetric) : tile.label,
            metric: nextMetric,
        })
    }

    const onOperatorChange = (operator: AccountsOverviewThresholdOperator): void => {
        if (tile.metric.type !== 'count_threshold') {
            return
        }
        const previousLabelLooksAuto = tile.label === defaultLabelForMetric(tile.metric)
        const nextMetric: AccountsOverviewTileMetric = { ...tile.metric, operator }
        onChange({
            label: previousLabelLooksAuto ? defaultLabelForMetric(nextMetric) : tile.label,
            metric: nextMetric,
        })
    }

    const onThresholdValueChange = (value: number): void => {
        if (tile.metric.type !== 'count_threshold') {
            return
        }
        const previousLabelLooksAuto = tile.label === defaultLabelForMetric(tile.metric)
        const nextMetric: AccountsOverviewTileMetric = { ...tile.metric, value }
        onChange({
            label: previousLabelLooksAuto ? defaultLabelForMetric(nextMetric) : tile.label,
            metric: nextMetric,
        })
    }

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Transform.toString(transform), transition }}
            {...attributes}
        >
            <div className="border border-border rounded p-3 flex flex-col gap-2 bg-surface-primary">
                <div className="flex items-center gap-2">
                    <span {...listeners} className="cursor-grab text-secondary">
                        <SortableDragIcon />
                    </span>
                    <LemonInput
                        value={tile.label}
                        onChange={(label) => onChange({ label, metric: tile.metric })}
                        placeholder="Tile label"
                        fullWidth
                        data-attr={`accounts-overview-tile-label-${tile.id}`}
                    />
                    <Tooltip title="Remove tile">
                        <LemonButton
                            onClick={onRemove}
                            status="danger"
                            size="small"
                            icon={<IconX />}
                            data-attr={`accounts-overview-tile-remove-${tile.id}`}
                        />
                    </Tooltip>
                </div>
                <div className="flex flex-wrap items-center gap-2 pl-6">
                    <LemonSelect
                        size="small"
                        value={tile.metric.type}
                        onChange={(value) => value && onMetricTypeChange(value)}
                        options={(Object.keys(METRIC_TYPE_LABELS) as AccountsOverviewTileMetricType[]).map((type) => ({
                            value: type,
                            label: METRIC_TYPE_LABELS[type],
                            disabledReason:
                                type !== 'count' && noNumericColumns ? 'No numeric columns available' : undefined,
                        }))}
                        data-attr={`accounts-overview-tile-metric-type-${tile.id}`}
                    />
                    {needsColumn ? (
                        <LemonSelect
                            size="small"
                            value={tile.metric.type === 'count' ? undefined : tile.metric.columnExpression}
                            onChange={(value) => value && onColumnChange(value)}
                            options={columnOptions}
                            disabledReason={noNumericColumns ? 'No numeric columns available' : undefined}
                            placeholder="Pick a column"
                            data-attr={`accounts-overview-tile-column-${tile.id}`}
                        />
                    ) : null}
                    {tile.metric.type === 'count_threshold' ? (
                        <>
                            <LemonSelect
                                size="small"
                                value={tile.metric.operator}
                                onChange={(value) => value && onOperatorChange(value)}
                                options={ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS.map((op) => ({
                                    value: op,
                                    label: op,
                                }))}
                                data-attr={`accounts-overview-tile-operator-${tile.id}`}
                            />
                            <LemonInput
                                type="number"
                                value={tile.metric.value}
                                onChange={(value) =>
                                    onThresholdValueChange(typeof value === 'number' ? value : Number(value) || 0)
                                }
                                data-attr={`accounts-overview-tile-threshold-${tile.id}`}
                            />
                        </>
                    ) : null}
                </div>
            </div>
        </div>
    )
}
