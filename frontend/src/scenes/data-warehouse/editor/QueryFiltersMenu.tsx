import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'

import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { TestAccountFilters } from '~/queries/nodes/DataNode/TestAccountFilters'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import type { HogQLFilters, HogQLQuery } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'

import { sqlEditorLogic } from './sqlEditorLogic'

const hasDateRange = (filters?: HogQLFilters): boolean => {
    return !!(filters?.dateRange?.date_from || filters?.dateRange?.date_to)
}

const hasPropertyFilters = (filters?: HogQLFilters): boolean => {
    return !!filters?.properties?.length
}

const hasActiveFilters = (filters?: HogQLFilters): boolean => {
    return hasDateRange(filters) || hasPropertyFilters(filters) || !!filters?.filterTestAccounts
}

const queryUsesFiltersPlaceholder = (query: string | null): boolean => {
    return !!query && (query.includes('{filters}') || query.includes('{filters.'))
}

export function QueryFiltersMenu(): JSX.Element | null {
    const { sourceQuery, queryInput } = useValues(sqlEditorLogic)
    const { setSourceQuery, runQuery, insertTextAtCursor } = useActions(sqlEditorLogic)
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    if (!isHogQLQuery(sourceQuery.source)) {
        return null
    }

    const source = sourceQuery.source
    const filters = source.filters
    const hasFilters = hasActiveFilters(filters)
    const usesFiltersPlaceholder = queryUsesFiltersPlaceholder(queryInput ?? source.query)

    const setHogQLQuery = (query: HogQLQuery): void => {
        const nextSourceQuery = {
            ...sourceQuery,
            source: query,
        }

        setSourceQuery(nextSourceQuery)

        if (usesFiltersPlaceholder) {
            runQuery(queryInput ?? query.query)
        }
    }

    const resetFilters = (): void => {
        setHogQLQuery({
            ...source,
            filters: {},
        })
    }

    const menuItems: LemonMenuItems = [
        {
            custom: true,
            label: () => (
                <div
                    className={`${CLICK_OUTSIDE_BLOCK_CLASS} w-[360px] max-w-[calc(100vw-2rem)] p-2 space-y-3`}
                    onClick={(event) => event.stopPropagation()}
                >
                    <div className="text-xs text-muted">
                        Use <code>{'{filters}'}</code> in your SQL query <code>where</code> clause to apply these
                        filters. Supported source tables are <code>events</code>, <code>sessions</code>,{' '}
                        <code>groups</code>.
                    </div>
                    <div className="space-y-1">
                        <div className="text-xs font-semibold">Time range</div>
                        <DateRange query={source} setQuery={setHogQLQuery} />
                    </div>
                    <div className="space-y-1">
                        <div className="text-xs font-semibold">Property filters</div>
                        <EventPropertyFilters query={source} setQuery={setHogQLQuery} />
                    </div>
                    <TestAccountFilters
                        query={source}
                        setQuery={(query) => {
                            if (isHogQLQuery(query)) {
                                setHogQLQuery(query)
                            }
                        }}
                    />
                    <div className="flex gap-2">
                        <LemonButton type="secondary" size="small" onClick={() => insertTextAtCursor('{filters}')}>
                            Insert placeholder
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={resetFilters}
                            disabledReason={!hasFilters ? 'No filters to reset' : undefined}
                        >
                            Reset filters
                        </LemonButton>
                    </div>
                </div>
            ),
        },
    ]

    return (
        <LemonMenu items={menuItems} visible={isMenuOpen} onVisibilityChange={setIsMenuOpen} closeOnClickInside={false}>
            <LemonButton
                type="secondary"
                size="small"
                icon={
                    <span className="relative inline-flex">
                        <IconFilter />
                        {hasFilters ? (
                            <span className="absolute -top-0.5 -right-1 block h-2 w-2 rounded-full bg-danger" />
                        ) : null}
                    </span>
                }
                data-attr="sql-editor-filters-button"
                tooltip={usesFiltersPlaceholder ? undefined : 'Insert {filters} into your SQL query to apply filters'}
            >
                Filters
            </LemonButton>
        </LemonMenu>
    )
}
