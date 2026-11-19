import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu } from '@posthog/lemon-ui'

import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'

import { MATERIALIZATION_STATUS_FILTER_OPTIONS } from 'products/data_warehouse/frontend/shared/filterMaterializedViewsByStatus'

import { queryDatabaseLogic } from './queryDatabaseLogic'

const MATERIALIZATION_STATUS_SEARCH_DATA = [
    [
        { label: 'status', value: 'status', hint: 'Materialization status', icon: <IconFilter /> },
        MATERIALIZATION_STATUS_FILTER_OPTIONS.map((status) => ({
            label: status,
            value: status.toLowerCase(),
        })),
        'Filter materialized views by their latest run',
    ],
] satisfies React.ComponentProps<typeof SearchAutocomplete>['searchData']

interface TreeSearchFieldProps {
    placeholder?: string
}

export function DatabaseSearchField({ placeholder }: TreeSearchFieldProps): JSX.Element {
    const { treeRef, searchTerm, connectionId, materializationStatusFilters } = useValues(queryDatabaseLogic)
    const { setSearchTerm, clearSearch, toggleMaterializationStatusFilter, clearMaterializationStatusFilters } =
        useActions(queryDatabaseLogic)

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault() // Prevent scrolling
            const visibleItems = treeRef?.current?.getVisibleItems()
            if (visibleItems && visibleItems.length > 0) {
                e.currentTarget.blur() // Remove focus from input
                treeRef?.current?.focusItem(visibleItems[0].id)
            }
        }
    }

    return (
        <div className="flex items-center gap-1 min-w-0">
            <div className="flex-1 min-w-0">
                <SearchAutocomplete
                    inputPlaceholder={placeholder}
                    defaultValue={searchTerm}
                    searchData={connectionId ? undefined : MATERIALIZATION_STATUS_SEARCH_DATA}
                    onKeyDown={(e) => handleKeyDown(e)}
                    onClear={() => clearSearch()}
                    onChange={(value) => setSearchTerm(value)}
                />
            </div>
            {!connectionId && (
                <LemonMenu
                    placement="bottom-end"
                    closeOnClickInside={false}
                    items={[
                        {
                            title: 'Materialization status',
                            items: MATERIALIZATION_STATUS_FILTER_OPTIONS.map((status) => ({
                                key: status,
                                label: status,
                                role: 'menuitemcheckbox',
                                'aria-checked': materializationStatusFilters.includes(status),
                                onClick: () => toggleMaterializationStatusFilter(status),
                                'data-attr':
                                    status === 'Failed'
                                        ? 'sql-editor-failed-materializations-filter'
                                        : `sql-editor-materialization-status-${status.toLowerCase()}`,
                                icon: (
                                    <LemonCheckbox
                                        checked={materializationStatusFilters.includes(status)}
                                        decorative
                                        className="pointer-events-none"
                                        size="small"
                                    />
                                ),
                            })),
                        },
                        {
                            items: [
                                {
                                    label: 'Clear filters',
                                    onClick: clearMaterializationStatusFilters,
                                    disabledReason:
                                        materializationStatusFilters.length === 0 ? 'No active filters' : null,
                                    'data-attr': 'sql-editor-clear-materialization-filters',
                                },
                            ],
                        },
                    ]}
                >
                    <LemonButton
                        icon={<IconFilter />}
                        size="small"
                        active={materializationStatusFilters.length > 0}
                        tooltip="Filter materialized views"
                        aria-label="Filter materialized views"
                        data-attr="sql-editor-table-filters-menu"
                    />
                </LemonMenu>
            )}
        </div>
    )
}
