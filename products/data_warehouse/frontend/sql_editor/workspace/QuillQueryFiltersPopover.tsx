import { IconFilter, IconWarning } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { useQueryFiltersState } from 'scenes/data-warehouse/editor/useQueryFiltersState'

import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { TestAccountFilters } from '~/queries/nodes/DataNode/TestAccountFilters'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { isHogQLQuery } from '~/queries/schema/node-guards'

// The date range and property filters inside are Lemon components that open their own popovers in a
// portal. Pressing or focusing inside one is outside this popover as far as Base UI can tell, so
// those dismissals are cancelled here, the way the Lemon menu used CLICK_OUTSIDE_BLOCK_CLASS.
type PopoverChangeDetails = Parameters<NonNullable<React.ComponentProps<typeof Popover>['onOpenChange']>>[1]

function keepOpenForNestedPopovers(open: boolean, details: PopoverChangeDetails): void {
    if (open || (details.reason !== 'outside-press' && details.reason !== 'focus-out')) {
        return
    }
    const event = details.event as (Event & { relatedTarget?: EventTarget | null }) | undefined
    const target = details.reason === 'focus-out' ? event?.relatedTarget : event?.target
    if (target instanceof Element && target.closest('.Popover, .LemonModal__layout')) {
        details.cancel()
    }
}

const FILTERS_DOCS_URL = 'https://posthog.com/docs/data-warehouse/sql/variables#applying-dashboard-filters'

/** The query's time range, property filters and test account toggle, applied through {filters}. */
export function QuillQueryFiltersPopover(): JSX.Element | null {
    const filtersState = useQueryFiltersState()

    if (!filtersState) {
        return null
    }

    const {
        source,
        hasFilters,
        filtersMissingPlaceholder,
        bindingsMissingTimestamp,
        tooltip,
        setHogQLQuery,
        resetFilters,
        insertPlaceholder,
    } = filtersState
    const hasWarning = filtersMissingPlaceholder || bindingsMissingTimestamp

    return (
        <Popover onOpenChange={keepOpenForNestedPopovers}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        tooltip={tooltip}
                        indicator={hasWarning ? 'warning' : hasFilters ? 'default' : undefined}
                        aria-label={hasWarning ? 'Filters, not applied' : hasFilters ? 'Filters on' : 'Filters'}
                        data-attr="sql-editor-filters-button"
                    />
                }
            >
                <IconFilter />
                <span className="@max-[44rem]/sql-workspace:hidden">Filters</span>
            </PopoverTrigger>
            <PopoverContent align="start" className="flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-3 p-3">
                {bindingsMissingTimestamp ? (
                    <Text size="xs" className="m-0 flex gap-1.5 text-warning-foreground">
                        <IconWarning className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                            This query binds its own columns with <code>{'{filters(...)}'}</code> but has no{' '}
                            <code>timestamp</code> key, so it can't take a date filter. Bind your time column, for
                            example <code>{'{filters(created_at AS timestamp)}'}</code>, or write{' '}
                            <code>null AS timestamp</code> to skip date filtering.{' '}
                            <Button
                                variant="link"
                                size="inline"
                                render={<LinkPrimitive to={FILTERS_DOCS_URL} target="_blank" />}
                            >
                                Learn more
                            </Button>
                        </span>
                    </Text>
                ) : filtersMissingPlaceholder ? (
                    <Text size="xs" className="m-0 flex gap-1.5 text-warning-foreground">
                        <IconWarning className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                            Filters are set, but the query has no <code>{'{filters}'}</code> placeholder, so they aren't
                            applied. Add <code>{'{filters}'}</code> to the <code>where</code> clause.{' '}
                            <Button
                                variant="link"
                                size="inline"
                                render={<LinkPrimitive to={FILTERS_DOCS_URL} target="_blank" />}
                            >
                                Learn more
                            </Button>
                        </span>
                    </Text>
                ) : (
                    <Text size="xs" className="m-0 text-muted-foreground">
                        Add <code>{'{filters}'}</code> to the <code>where</code> clause to apply these filters to
                        PostHog tables like <code>events</code>. For other tables, bind your own columns, for example{' '}
                        <code>{"{filters(created_at AS timestamp, plan AS 'plan')}"}</code>.{' '}
                        <Button
                            variant="link"
                            size="inline"
                            render={<LinkPrimitive to={FILTERS_DOCS_URL} target="_blank" />}
                        >
                            Learn more
                        </Button>
                    </Text>
                )}
                <div className="flex flex-col gap-1">
                    <Text size="xs" className="m-0 font-semibold">
                        Time range
                    </Text>
                    <DateRange query={source} setQuery={setHogQLQuery} />
                </div>
                <div className="flex flex-col gap-1">
                    <Text size="xs" className="m-0 font-semibold">
                        Property filters
                    </Text>
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
                <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={insertPlaceholder}>
                        Insert placeholder
                    </Button>
                    <Button
                        variant="outline"
                        onClick={resetFilters}
                        disabledReason={!hasFilters ? 'No filters to reset' : undefined}
                    >
                        Reset filters
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    )
}
