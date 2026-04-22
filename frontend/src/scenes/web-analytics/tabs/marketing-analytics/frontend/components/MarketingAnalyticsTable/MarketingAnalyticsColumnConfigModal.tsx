import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
    const marketingQuery = useMemo(() => rawQuery?.source as MarketingAnalyticsTableQuery | undefined, [rawQuery])

    // Local draft state — changes are buffered here until the user applies them
    const [draftSelect, setDraftSelect] = useState<string[]>(marketingQuery?.select || sortedColumns)
    const [draftOrderBy, setDraftOrderBy] = useState<[string, string][] | undefined>(marketingQuery?.orderBy)
    const [draftPinnedColumns, setDraftPinnedColumns] = useState<string[]>(rawQuery?.pinnedColumns || [])

    // Keep a ref to the latest query values so the open-effect can read them without being a dependency
    const latestQueryRef = useRef({ marketingQuery, sortedColumns, rawQuery })
    useEffect(() => {
        latestQueryRef.current = { marketingQuery, sortedColumns, rawQuery }
    })

    // Sync draft state when the modal opens
    useEffect(() => {
        if (columnConfigModalVisible) {
            const { marketingQuery: mq, sortedColumns: sc, rawQuery: rq } = latestQueryRef.current
            setDraftSelect(mq?.select || sc)
            setDraftOrderBy(mq?.orderBy)
            setDraftPinnedColumns(rq?.pinnedColumns || [])
        }
    }, [columnConfigModalVisible])

    // Derived state from draft
    const [currentSortColumn, currentSortDirection] = useMemo(
        () => (draftOrderBy?.[0] || []) as [string | undefined, 'ASC' | 'DESC' | undefined],
        [draftOrderBy]
    )

    const hiddenColumns = useMemo(
        () => sortedColumns.filter((column: string) => !draftSelect.includes(column)),
        [draftSelect, sortedColumns]
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

    const applyChanges = useCallback(() => {
        setQuery({
            ...rawQuery,
            source: {
                ...marketingQuery,
                select: draftSelect,
                orderBy: draftOrderBy,
            },
            pinnedColumns: draftPinnedColumns,
        } as DataTableNode)
        hideColumnConfigModal()
    }, [rawQuery, marketingQuery, draftSelect, draftOrderBy, draftPinnedColumns, setQuery, hideColumnConfigModal])

    const clearOrderBy = useCallback(() => {
        setDraftOrderBy(undefined)
    }, [])

    const showColumn = useCallback(
        (columnName: string) => {
            const newSelect: string[] = []
            for (const column of sortedColumns) {
                if (column === columnName || !hiddenColumns.includes(column)) {
                    newSelect.push(column)
                }
            }
            setDraftSelect(newSelect)
        },
        [hiddenColumns, sortedColumns]
    )

    const updateOrderBy = useCallback(
        (columnName: string, direction: 'ASC' | 'DESC') => {
            if (hiddenColumns.includes(columnName)) {
                showColumn(columnName)
            }
            setDraftOrderBy(createMarketingAnalyticsOrderBy(columnName, direction))
        },
        [hiddenColumns, showColumn]
    )

    const handleSortToggle = useCallback(
        (columnName: string, direction: 'ASC' | 'DESC') => {
            if (currentSortColumn === columnName && currentSortDirection === direction) {
                clearOrderBy()
            } else {
                updateOrderBy(columnName, direction)
            }
        },
        [currentSortColumn, currentSortDirection, clearOrderBy, updateOrderBy]
    )

    const toggleColumnVisibility = useCallback(
        (columnName: string) => {
            const isCurrentlyHidden = hiddenColumns.includes(columnName)

            if (isCurrentlyHidden) {
                showColumn(columnName)
            } else {
                // Hiding a column
                const newSelect: string[] = []
                for (const column of sortedColumns) {
                    if (column !== columnName && !hiddenColumns.includes(column)) {
                        newSelect.push(column)
                    }
                }
                setDraftSelect(newSelect)

                // Remove from sorting if needed
                if (draftOrderBy?.[0]?.[0] === columnName) {
                    setDraftOrderBy(undefined)
                }

                // Remove from pinned columns
                setDraftPinnedColumns((prev) => prev.filter((c) => c !== columnName))
            }
        },
        [hiddenColumns, sortedColumns, draftOrderBy, showColumn]
    )

    const toggleColumnPinning = useCallback(
        (columnName: string) => {
            const isCurrentlyPinned = draftPinnedColumns.includes(columnName)

            if (isCurrentlyPinned) {
                setDraftPinnedColumns((prev) => prev.filter((c) => c !== columnName))
            } else {
                setDraftPinnedColumns((prev) => [...prev, columnName])

                // If pinning a hidden column, show it
                if (hiddenColumns.includes(columnName)) {
                    showColumn(columnName)
                }
            }
        },
        [draftPinnedColumns, hiddenColumns, showColumn]
    )

    const resetColumnConfigToDefaults = useCallback(() => {
        setDraftSelect(sortedColumns)
        setDraftOrderBy(undefined)
        setDraftPinnedColumns([])
    }, [sortedColumns])

    // Check if there are pending changes
    const hasChanges = useMemo(() => {
        const currentSelect = marketingQuery?.select || sortedColumns
        const currentOrderBy = marketingQuery?.orderBy
        const currentPinned = rawQuery?.pinnedColumns || []

        return (
            JSON.stringify(draftSelect) !== JSON.stringify(currentSelect) ||
            JSON.stringify(draftOrderBy) !== JSON.stringify(currentOrderBy) ||
            JSON.stringify(draftPinnedColumns) !== JSON.stringify(currentPinned)
        )
    }, [draftSelect, draftOrderBy, draftPinnedColumns, marketingQuery, rawQuery, sortedColumns])

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
                        // Intentionally checks draft vs defaults (not vs committed state like hasChanges),
                        // so this stays enabled when the committed config is non-default
                        disabledReason={
                            draftPinnedColumns.length === 0 &&
                            !draftOrderBy &&
                            hiddenColumns.length === 0 &&
                            draftSelect.length === sortedColumns.length
                                ? 'Already at defaults'
                                : undefined
                        }
                    >
                        Reset to defaults
                    </LemonButton>
                    <div className="flex items-center gap-1">
                        <LemonButton type="secondary" onClick={hideColumnConfigModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={applyChanges}
                            disabledReason={!hasChanges ? 'No changes to apply' : undefined}
                        >
                            Apply
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
                        {draftOrderBy ? (
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
                        {draftPinnedColumns.length > 0 ? (
                            <div className="flex items-center gap-1 text-sm">
                                <IconPinFilled className="text-xs text-primary" />
                                <span className="text-muted">
                                    Pinned:{' '}
                                    <span className="font-medium text-primary">{draftPinnedColumns.join(', ')}</span>
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
                                            clearOrderBy()
                                        } else if (currentSortDirection) {
                                            updateOrderBy(value, currentSortDirection)
                                        } else {
                                            updateOrderBy(value, 'ASC')
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
                                            clearOrderBy()
                                        } else if (currentSortColumn) {
                                            updateOrderBy(currentSortColumn, value)
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
                        {sortedColumns.map((columnName: string) => {
                            const isHidden = hiddenColumns.includes(columnName)
                            const isPinned = draftPinnedColumns.includes(columnName)
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
