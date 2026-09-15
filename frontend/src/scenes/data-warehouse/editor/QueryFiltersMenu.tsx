import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconWarning } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, Link } from '@posthog/lemon-ui'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'

import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { TestAccountFilters } from '~/queries/nodes/DataNode/TestAccountFilters'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import type { HogQLFilters, HogQLQuery } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'

import { filtersPlaceholderBindings, queryUsesFiltersPlaceholder } from './sql-utils'
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

const filtersTooltip = ({
    filtersMissingPlaceholder,
    bindingsMissingTimestamp,
    usesFiltersPlaceholder,
}: {
    filtersMissingPlaceholder: boolean
    bindingsMissingTimestamp: boolean
    usesFiltersPlaceholder: boolean
}): string | undefined => {
    if (filtersMissingPlaceholder) {
        return "Filters are present, but this SQL query doesn't include a {filters} tag"
    }
    if (bindingsMissingTimestamp) {
        return "This query's {filters(...)} bindings have no timestamp key, so it can't take a date filter"
    }
    if (!usesFiltersPlaceholder) {
        return 'Insert {filters} into your SQL query to apply filters'
    }
    return undefined
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
    const queryText = queryInput ?? source.query
    const usesFiltersPlaceholder = queryUsesFiltersPlaceholder(queryText)
    const filtersMissingPlaceholder = hasFilters && !usesFiltersPlaceholder
    const bindings = filtersPlaceholderBindings(queryText)
    const bindingsMissingTimestamp = bindings !== null && !bindings.includes('timestamp')

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
                    {bindingsMissingTimestamp ? (
                        <div className="text-xs text-warning">
                            This query binds its own columns with <code>{'{filters(...)}'}</code> but has no{' '}
                            <code>timestamp</code> key, so it can't take a date filter. A dashboard applies its date
                            range to every tile, so the query fails once you add it to one. Bind your time column, for
                            example <code>{'{filters(created_at AS timestamp)}'}</code>, or write{' '}
                            <code>null AS timestamp</code> to exempt the query from date filtering.{' '}
                            <Link
                                to="https://posthog.com/docs/data-warehouse/sql/variables#applying-dashboard-filters"
                                target="_blank"
                            >
                                Learn more
                            </Link>
                        </div>
                    ) : filtersMissingPlaceholder ? (
                        <div className="text-xs text-warning">
                            Filters are set, but this SQL query doesn't include a <code>{'{filters}'}</code>{' '}
                            placeholder, so they aren't applied. Add <code>{'{filters}'}</code> to your{' '}
                            <code>where</code> clause when selecting from PostHog tables like <code>events</code>,{' '}
                            <code>persons</code>, <code>groups</code>, or <code>sessions</code>. For any other table or
                            view, bind your own columns, for example{' '}
                            <code>{"{filters(created_at AS timestamp, plan AS 'plan')}"}</code>.{' '}
                            <Link
                                to="https://posthog.com/docs/data-warehouse/sql/variables#applying-dashboard-filters"
                                target="_blank"
                            >
                                Learn more
                            </Link>
                        </div>
                    ) : (
                        <div className="text-xs text-muted">
                            Use <code>{'{filters}'}</code> in your SQL query <code>where</code> clause to apply these
                            filters when selecting from PostHog tables like <code>events</code>, <code>persons</code>,{' '}
                            <code>groups</code>, or <code>sessions</code>. For any other table or view, bind your own
                            columns, for example <code>{"{filters(created_at AS timestamp, plan AS 'plan')}"}</code>.{' '}
                            <Link
                                to="https://posthog.com/docs/data-warehouse/sql/variables#applying-dashboard-filters"
                                target="_blank"
                            >
                                Learn more
                            </Link>
                        </div>
                    )}
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
                sideIcon={
                    filtersMissingPlaceholder || bindingsMissingTimestamp ? (
                        <IconWarning className="text-warning" />
                    ) : undefined
                }
                tooltip={filtersTooltip({
                    filtersMissingPlaceholder,
                    bindingsMissingTimestamp,
                    usesFiltersPlaceholder,
                })}
            >
                Filters
            </LemonButton>
        </LemonMenu>
    )
}
