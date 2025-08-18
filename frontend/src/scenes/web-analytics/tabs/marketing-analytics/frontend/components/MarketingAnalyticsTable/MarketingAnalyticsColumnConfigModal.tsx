import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { IconEye, IconHide, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { MarketingAnalyticsTableQuery } from '~/queries/schema/schema-general'
import { DataTableNode } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsTableLogic } from '../../logic/marketingAnalyticsTableLogic'
import { createMarketingAnalyticsOrderBy } from '../../logic/utils'

const directionOptions = [
    { label: 'No direction', value: null },
    { label: 'Ascending', value: 'ASC' as const, icon: <IconArrowUp /> },
    { label: 'Descending', value: 'DESC' as const, icon: <IconArrowDown /> },
]

export function MarketingAnalyticsColumnConfigModal({ query: rawQuery }: { query: DataTableNode }): JSX.Element {
    const { columnConfigModalVisible } = useValues(marketingAnalyticsLogic)
    const { hideColumnConfigModal } = useActions(marketingAnalyticsLogic)
    const { sortedColumns } = useValues(marketingAnalyticsTableLogic)
    const { setQuery } = useActions(marketingAnalyticsTableLogic)
    // useRef to avoid re-rendering the component when we pin columns but after we rerender the component we need to keep the sorted columns
    const staticSortedColumns = useRef(sortedColumns)
    const marketingQuery = useMemo(() => rawQuery?.source as MarketingAnalyticsTableQuery | undefined, [rawQuery])

    // Get current sort column and direction
    const [currentSortColumn, currentSortDirection] = useMemo(
        () => marketingQuery?.orderBy?.[0] || [],
        [marketingQuery?.orderBy]
    )
    // hidden columns are the difference between default columns and the query columns
    const hiddenColumns = useMemo(
        () =>
            marketingQuery?.select
                ? sortedColumns.filter((column: string) => !marketingQuery?.select?.includes(column))
                : [],
        [marketingQuery?.select, sortedColumns]
    )
    const sortOptions = useMemo(
        () => [
            { label: 'No sorting', value: null },
            ...sortedColumns
                .filter((column: string) => !hiddenColumns.includes(column))
                .map((column: string) => ({
                    label: column,
                    value: column,
                })),
        ],
        [hiddenColumns, sortedColumns]
    )
    const pinnedColumns = useMemo(() => rawQuery?.pinnedColumns || [], [rawQuery])

    const clearMarketingAnalyticsOrderBy = useCallback(() => {
        if (rawQuery) {
            setQuery({
                ...rawQuery,
                source: {
                    ...rawQuery.source,
                    orderBy: undefined,
                },
            } as DataTableNode)
        }
    }, [rawQuery, setQuery])

    const setMarketingAnalyticsOrderBy = useCallback(
        (columnName: string, direction: 'ASC' | 'DESC') => {
            let newSelect = []
            // If the column is hidden, we need to show it by adding it to select
            if (hiddenColumns.includes(columnName)) {
                for (const column of sortedColumns) {
                    if (column === columnName || !hiddenColumns.includes(column)) {
                        newSelect.push(column)
                    }
                }
            } else {
                newSelect = marketingQuery?.select || []
            }

            if (rawQuery && marketingQuery) {
                setQuery({
                    ...rawQuery,
                    source: {
                        ...marketingQuery,
                        select: newSelect,
                        orderBy: createMarketingAnalyticsOrderBy(columnName, direction),
                    },
                })
            }
        },
        [hiddenColumns, marketingQuery, rawQuery, setQuery, sortedColumns]
    )

    const handleSortToggle = useCallback(
        (columnName: string, direction: 'ASC' | 'DESC') => {
            if (currentSortColumn === columnName && currentSortDirection === direction) {
                // If already sorting by this column in this direction, clear sort
                clearMarketingAnalyticsOrderBy()
            } else {
                // Set this column with the specified direction
                setMarketingAnalyticsOrderBy(columnName, direction)
            }
        },
        [currentSortColumn, currentSortDirection, clearMarketingAnalyticsOrderBy, setMarketingAnalyticsOrderBy]
    )

    const toggleColumnVisibility = useCallback(
        (columnName: string) => {
            const isCurrentlyHidden = hiddenColumns.includes(columnName)
            const newSelect = []
            let newOrderBy = marketingQuery?.orderBy || []
            let newPinnedColumns = [...pinnedColumns]

            if (isCurrentlyHidden) {
                // Showing a column - add it to select and preserve existing sort/pin
                for (const column of sortedColumns) {
                    if (column === columnName || !hiddenColumns.includes(column)) {
                        newSelect.push(column)
                    }
                }
            } else {
                // Hiding a column - remove it from select, sort, and pin
                for (const column of sortedColumns) {
                    if (column !== columnName && !hiddenColumns.includes(column)) {
                        newSelect.push(column)
                    }
                }

                // Remove from sorting if this column was being sorted
                if (marketingQuery?.orderBy?.[0]?.[0] === columnName) {
                    newOrderBy = []
                }

                // Remove from pinned columns
                const pinnedIndex = newPinnedColumns.indexOf(columnName)
                if (pinnedIndex > -1) {
                    newPinnedColumns.splice(pinnedIndex, 1)
                }
            }

            setQuery({
                ...rawQuery,
                source: {
                    ...marketingQuery,
                    select: newSelect,
                    orderBy: newOrderBy,
                },
                pinnedColumns: newPinnedColumns,
            } as DataTableNode)
        },
        [hiddenColumns, marketingQuery, rawQuery, setQuery, sortedColumns, pinnedColumns]
    )

    const toggleColumnPinning = useCallback(
        (columnName: string) => {
            const newPinnedColumns = [...pinnedColumns]
            const isCurrentlyPinned = newPinnedColumns.includes(columnName)

            if (isCurrentlyPinned) {
                // Unpinning - just remove from pinned columns
                newPinnedColumns.splice(newPinnedColumns.indexOf(columnName), 1)
            } else {
                // Pinning - add to pinned columns and show if hidden
                newPinnedColumns.push(columnName)
            }

            let newSelect = marketingQuery?.select || []

            // If we're pinning a hidden column, show it
            if (!isCurrentlyPinned && hiddenColumns.includes(columnName)) {
                newSelect = []
                for (const column of sortedColumns) {
                    if (column === columnName || !hiddenColumns.includes(column)) {
                        newSelect.push(column)
                    }
                }
            }

            setQuery({
                ...rawQuery,
                source: {
                    ...marketingQuery,
                    select: newSelect,
                },
                pinnedColumns: newPinnedColumns,
            } as DataTableNode)
        },
        [pinnedColumns, rawQuery, setQuery, marketingQuery, hiddenColumns, sortedColumns]
    )

    const resetColumnConfigToDefaults = useCallback(() => {
        setQuery({
            ...rawQuery,
            source: {
                ...marketingQuery,
                select: sortedColumns,
                orderBy: undefined,
            },
            pinnedColumns: [],
        } as DataTableNode)
    }, [marketingQuery, rawQuery, setQuery, sortedColumns])

    return (
        <LemonModal
            isOpen={columnConfigModalVisible}
            onClose={hideColumnConfigModal}
            title="Configure columns"
            width={600}
            footer={
                <div className="flex justify-between items-center w-full">
                    <LemonButton
                        type="secondary"
                        onClick={resetColumnConfigToDefaults}
                        disabledReason={
                            pinnedColumns.length === 0 &&
                            !marketingQuery?.orderBy &&
                            hiddenColumns.length === 0 &&
                            marketingQuery?.select?.length === sortedColumns.length
                                ? 'No changes to revert'
                                : undefined
                        }
                    >
                        Reset to defaults
                    </LemonButton>
                    <div className="flex items-center gap-1">
                        <LemonButton type="secondary" onClick={hideColumnConfigModal}>
                            Close
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-6">
                {/* Active Filters Section - Always Visible */}
                <div className="p-4 bg-bg-light border rounded">
                    <h5 className="font-medium mb-3 text-sm uppercase tracking-wide text-muted">Active filters</h5>
                    <div className="space-y-2">
                        {marketingQuery?.orderBy ? (
                            <div className="flex items-center gap-1 text-sm">
                                <IconArrowUp className="text-xs text-primary" />
                                <span className="text-muted">
                                    Sorted by: <span className="font-medium text-primary">{currentSortColumn}</span> (
                                    {currentSortDirection})
                                </span>
                            </div>
                        ) : (
                            <div className="text-sm text-muted italic">No sorting applied</div>
                        )}
                        {hiddenColumns.length > 0 ? (
                            <div className="flex items-center gap-1 text-sm">
                                <IconHide className="text-xs text-muted" />
                                <span className="text-muted">
                                    Hidden: <span className="font-medium">{hiddenColumns.join(', ')}</span>
                                </span>
                            </div>
                        ) : (
                            <div className="text-sm text-muted italic">No hidden columns</div>
                        )}
                        {pinnedColumns.length > 0 ? (
                            <div className="flex items-center gap-1 text-sm">
                                <IconPinFilled className="text-xs text-primary" />
                                <span className="text-muted">
                                    Pinned: <span className="font-medium text-primary">{pinnedColumns.join(', ')}</span>
                                </span>
                            </div>
                        ) : (
                            <div className="text-sm text-muted italic">No pinned columns</div>
                        )}
                    </div>
                </div>

                {/* Sorting Section */}
                <div>
                    <h4 className="font-semibold mb-3">Sorting</h4>
                    <div className="space-y-1">
                        <div className="flex items-center gap-1">
                            <label className="text-sm font-medium text-muted min-w-20">Sort by:</label>
                            <div className="flex-1">
                                <LemonSelect
                                    value={currentSortColumn}
                                    onChange={(value) => {
                                        if (value === null) {
                                            clearMarketingAnalyticsOrderBy()
                                        } else if (currentSortDirection) {
                                            setMarketingAnalyticsOrderBy(value, currentSortDirection)
                                        } else {
                                            // If no direction is set, default to ASC
                                            setMarketingAnalyticsOrderBy(value, 'ASC')
                                        }
                                    }}
                                    options={sortOptions}
                                    placeholder="Select column..."
                                    fullWidth
                                    size="small"
                                />
                            </div>
                        </div>
                        <div className="flex items-center gap-1">
                            <label className="text-sm font-medium text-muted min-w-20">Direction:</label>
                            <div className="flex-1">
                                <LemonSelect
                                    value={currentSortDirection}
                                    onChange={(value) => {
                                        if (value === null) {
                                            // Clear sorting if "No direction" is selected
                                            clearMarketingAnalyticsOrderBy()
                                        } else if (currentSortColumn) {
                                            setMarketingAnalyticsOrderBy(currentSortColumn, value)
                                        }
                                    }}
                                    options={directionOptions}
                                    placeholder="Select direction..."
                                    fullWidth
                                    size="small"
                                    disabled={!currentSortColumn}
                                />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Column Management Section */}
                <div>
                    <h4 className="font-semibold mb-3">Column visibility and pinning</h4>
                    <p className="text-sm text-muted mb-2">
                        Hide columns you don't need or pin important ones to keep them always visible.
                    </p>

                    <div className="space-y-2">
                        {staticSortedColumns.current.map((columnName: string) => {
                            const isHidden = hiddenColumns.includes(columnName)
                            const isPinned = pinnedColumns.includes(columnName)
                            const isSortedByThisColumn = currentSortColumn === columnName
                            const isAscending = currentSortDirection === 'ASC'

                            return (
                                <div
                                    key={columnName}
                                    className="flex items-center justify-between p-1 border rounded hover:bg-bg-light transition-colors"
                                >
                                    <div className="flex items-center gap-3 flex-1 min-w-0">
                                        <LemonCheckbox
                                            checked={!isHidden}
                                            onChange={() => toggleColumnVisibility(columnName)}
                                            label={<span className="flex items-center gap-1">{columnName}</span>}
                                            className="flex-1"
                                        />
                                    </div>
                                    <div className="flex items-center gap-1 flex-shrink-0">
                                        {/* Sort buttons */}
                                        <LemonButton
                                            size="small"
                                            icon={<IconArrowUp />}
                                            onClick={() => handleSortToggle(columnName, 'ASC')}
                                            tooltip={
                                                isSortedByThisColumn && isAscending ? 'Remove sort' : 'Sort ascending'
                                            }
                                            type={isSortedByThisColumn && isAscending ? 'primary' : 'secondary'}
                                        />
                                        <LemonButton
                                            size="small"
                                            icon={<IconArrowDown />}
                                            onClick={() => handleSortToggle(columnName, 'DESC')}
                                            tooltip={
                                                isSortedByThisColumn && !isAscending ? 'Remove sort' : 'Sort descending'
                                            }
                                            type={isSortedByThisColumn && !isAscending ? 'primary' : 'secondary'}
                                        />
                                        {/* Pin button */}
                                        <LemonButton
                                            size="small"
                                            icon={isPinned ? <IconPinFilled /> : <IconPin />}
                                            onClick={() => toggleColumnPinning(columnName)}
                                            tooltip={isPinned ? 'Unpin column' : 'Pin column'}
                                            type={isPinned ? 'primary' : 'secondary'}
                                        />
                                        {/* Visibility button */}
                                        <LemonButton
                                            size="small"
                                            icon={isHidden ? <IconHide /> : <IconEye />}
                                            onClick={() => toggleColumnVisibility(columnName)}
                                            tooltip={isHidden ? 'Show column' : 'Hide column'}
                                            type={isHidden ? 'primary' : 'secondary'}
                                        />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
