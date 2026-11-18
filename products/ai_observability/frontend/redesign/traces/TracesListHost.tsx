import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'

import { groupsModel } from '~/models/groupsModel'

import { AiObservabilityTracesListView, type TraceListItemApi } from '../../generated/api.schemas'
import { ListEmptyState } from '../lists/components/ListEmptyState'
import { ListErrorState } from '../lists/components/ListErrorState'
import { ListTable } from '../lists/components/ListTable'
import { ListToolbar } from '../lists/components/ListToolbar'
import { QuickFilterChips } from '../lists/components/QuickFilterChips'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { TraceDrawerListId } from '../trace/traceDrawerLists'
import { TraceDrawerRowsSync, useTraceDrawerTable, useTraceFullPageHref } from '../trace/TraceDrawerRowsHost'
import { TraceListRow } from '../trace/traceListRows'
import { tracesTableColumns } from './components/TracesTableColumns'
import { traceCellsLogic } from './traceCellsLogic'
import { TRACES_LIST_FILTERS, tracesListLogic } from './tracesListLogic'

// pinned: autocapture dashboards and tests select the list and its controls by this value and the suffixes built on it
const DATA_ATTR = 'ai-observability-traces-list'
const LIST_ID: TraceDrawerListId = 'traces'
const TRACE_LINK = '[data-attr="trace-name-link"]'

function toRow(item: TraceListItemApi): TraceListRow {
    return { traceId: item.id, timestamp: item.createdAt, stepId: null }
}

export function TracesListHost(): JSX.Element {
    const { items, counts, state, refreshing, canShowPrevious, canShowNext, filterTestAccounts, searchEnabled } =
        useValues(tracesListLogic)
    const { showPreviousPage, showNextPage, reload } = useActions(tracesListLogic)
    const { filters, searchDraft } = useValues(listFiltersLogic(TRACES_LIST_FILTERS))
    const { setPropertyFilters, setFilterTestAccounts, setSearchDraft, toggleQuickFilter, resetFilters } = useActions(
        listFiltersLogic(TRACES_LIST_FILTERS)
    )
    const { previews, people, sentiments } = useValues(traceCellsLogic)
    const { dateFrom, dateTo } = useValues(shellScopeLogic)
    const { setDateRange } = useActions(shellScopeLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const fullPageHref = useTraceFullPageHref(LIST_ID)
    const linkTo = useCallback((item: TraceListItemApi): string => fullPageHref(toRow(item)), [fullPageHref])
    const columns = useMemo(
        () => tracesTableColumns({ linkTo, cells: { previews, people, sentiments } }),
        [linkTo, previews, people, sentiments]
    )
    const drawerRows = useMemo(() => items.map(toRow), [items])
    const { onRow } = useTraceDrawerTable(LIST_ID, TRACE_LINK, toRow)

    return (
        <div className="flex flex-col gap-3">
            <QuickFilterChips
                chips={[
                    {
                        id: AiObservabilityTracesListView.Errors,
                        label: 'Errors',
                        count: counts?.errors ?? null,
                        tone: 'danger',
                    },
                    {
                        id: AiObservabilityTracesListView.Feedback,
                        label: 'User feedback',
                        count: counts?.feedback ?? null,
                    },
                ]}
                active={filters.quickFilter}
                onToggle={toggleQuickFilter}
                data-attr={DATA_ATTR}
            />
            <ListToolbar
                search={searchDraft}
                onSearchChange={searchEnabled ? setSearchDraft : undefined}
                searchPlaceholder="Search inputs and outputs"
                filters={
                    <PropertyFilters
                        propertyFilters={filters.propertyFilters}
                        onChange={setPropertyFilters}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                        pageKey={DATA_ATTR}
                    />
                }
                testAccounts={
                    <TestAccountFilterSwitch
                        checked={filterTestAccounts}
                        onChange={setFilterTestAccounts}
                        size="small"
                    />
                }
                dateRange={<DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDateRange} size="small" />}
                onReload={reload}
                reloading={state === 'loading' || refreshing}
                data-attr={DATA_ATTR}
            />
            <ListTable<TraceListItemApi>
                state={state}
                columns={columns}
                rows={items}
                rowKey={(item) => item.id}
                refreshing={refreshing}
                onRow={onRow}
                onPrevious={canShowPrevious ? showPreviousPage : undefined}
                onNext={canShowNext ? showNextPage : undefined}
                emptyState={
                    <ListEmptyState
                        title="No traces in this date range"
                        description="Pick a wider date range to see older traces."
                    />
                }
                emptyFilteredState={
                    <ListEmptyState
                        title="No traces match"
                        description="Change or clear the filters to see more traces."
                        action={{
                            label: 'Clear filters',
                            onClick: resetFilters,
                            'data-attr': `${DATA_ATTR}-clear-filters`,
                        }}
                    />
                }
                errorState={
                    <ListErrorState
                        title="Could not load traces"
                        description="Try again. If it keeps happening, contact support."
                        retry={{ onClick: reload, 'data-attr': `${DATA_ATTR}-retry` }}
                    />
                }
                data-attr={DATA_ATTR}
            />
            <TraceDrawerRowsSync listId={LIST_ID} rows={drawerRows} />
            <TraceDrawerHost listId={LIST_ID} />
        </div>
    )
}
