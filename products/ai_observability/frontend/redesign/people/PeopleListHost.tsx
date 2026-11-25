import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { MouseEvent, useCallback, useMemo } from 'react'

import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'

import {
    AiObservabilityPeopleListOrder,
    AiObservabilityPeopleListView,
    type PersonListItemApi,
} from '../../generated/api.schemas'
import { ListEmptyState } from '../lists/components/ListEmptyState'
import { ListErrorState } from '../lists/components/ListErrorState'
import { ListTable } from '../lists/components/ListTable'
import { ListToolbar } from '../lists/components/ListToolbar'
import { QuickFilterChips } from '../lists/components/QuickFilterChips'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellDocsUrl, shellHref, shellLinkParams } from '../shell/shellNavigation'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TRACE_DRAWER_OPEN_ROW_CLASS, hasOwnClickHandler } from '../trace/traceDrawerRows'
import { PeopleSetupCard } from './components/PeopleSetupCard'
import { peopleTableColumns } from './components/PeopleTableColumns'
import { PEOPLE_LIST_FILTERS, peopleListLogic } from './peopleListLogic'
import { personCellsLogic } from './personCellsLogic'

// pinned: autocapture dashboards and tests select the list and its controls by this value and the suffixes built on it
const DATA_ATTR = 'ai-observability-people-list'
const DOCS_URL = shellDocsUrl({ tab: 'people', scope: null })

const ORDER_OPTIONS = [
    { value: AiObservabilityPeopleListOrder.LastSeen, label: 'Sort by last seen' },
    { value: AiObservabilityPeopleListOrder.Cost, label: 'Sort by cost' },
]

export function PeopleListHost(): JSX.Element {
    const {
        items,
        newCount,
        newCountLoading,
        lookbackDays,
        state,
        refreshing,
        needsIdentification,
        order,
        includeAnonymous,
        personSearch,
        previousPageOffset,
        nextPageOffset,
        openPersonId,
    } = useValues(peopleListLogic)
    const { setOrder, setIncludeAnonymous, setPersonSearch, setOffset, openPerson, reload } =
        useActions(peopleListLogic)
    const { filters } = useValues(listFiltersLogic(PEOPLE_LIST_FILTERS))
    const { setPropertyFilters, toggleQuickFilter, clearFilters } = useActions(listFiltersLogic(PEOPLE_LIST_FILTERS))
    const { firstSeen } = useValues(personCellsLogic)
    const { dateFrom, dateTo, filterTestAccounts } = useValues(shellScopeLogic)
    const { setDateRange, setFilterTestAccounts } = useActions(shellScopeLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { searchParams } = useValues(router)

    const columns = useMemo(() => peopleTableColumns({ firstSeen }), [firstSeen])
    const onRow = useCallback(
        (item: PersonListItemApi) => ({
            className: item.id === openPersonId ? `cursor-pointer ${TRACE_DRAWER_OPEN_ROW_CLASS}` : 'cursor-pointer',
            // The row opens the person, except where a cell has its own link or button, such as the person's chip.
            onClick: ({ target, currentTarget }: MouseEvent<HTMLElement>) => {
                // React also bubbles a click from a portal, such as the chip's hover card, up to the row.
                if (target instanceof Node && currentTarget.contains(target) && !hasOwnClickHandler(target)) {
                    openPerson(item.id)
                }
            },
        }),
        [openPerson, openPersonId]
    )

    return (
        <div className="flex flex-col gap-3">
            <QuickFilterChips
                chips={[
                    {
                        id: AiObservabilityPeopleListView.New,
                        label: 'New',
                        count: newCount,
                        countLoading: newCountLoading,
                        tooltip:
                            lookbackDays !== null
                                ? `First AI activity in this range, none in the ${lookbackDays} days before it.`
                                : undefined,
                    },
                ]}
                active={filters.quickFilter}
                onToggle={toggleQuickFilter}
                data-attr={DATA_ATTR}
            />
            <ListToolbar
                search={personSearch}
                onSearchChange={setPersonSearch}
                searchPlaceholder="Search people"
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
                trailing={
                    <>
                        <LemonSwitch
                            bordered
                            size="small"
                            checked={includeAnonymous}
                            onChange={setIncludeAnonymous}
                            label="Include anonymous"
                            // pinned: autocapture dashboards and tests select the switch by this value
                            data-attr="ai-observability-people-include-anonymous"
                        />
                        <LemonSelect
                            size="small"
                            value={order}
                            options={ORDER_OPTIONS}
                            onChange={setOrder}
                            // pinned: autocapture dashboards and tests select the order by this value
                            data-attr={`${DATA_ATTR}-order`}
                        />
                    </>
                }
                dateRange={<DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDateRange} size="small" />}
                onReload={reload}
                reloading={state === 'loading' || refreshing}
                data-attr={DATA_ATTR}
            />
            {/* Outside the table, whose scroll area is wider than a narrow list, so the card's text wraps. */}
            {needsIdentification ? (
                <PeopleSetupCard
                    docsUrl={DOCS_URL}
                    tracesHref={shellHref(urls.aiObservabilityTraces(), shellLinkParams(searchParams))}
                />
            ) : (
                <ListTable<PersonListItemApi>
                    state={state}
                    columns={columns}
                    rows={items}
                    rowKey={(item) => item.id}
                    refreshing={refreshing}
                    onRow={onRow}
                    onPrevious={previousPageOffset !== null ? () => setOffset(previousPageOffset) : undefined}
                    onNext={nextPageOffset !== null ? () => setOffset(nextPageOffset) : undefined}
                    emptyState={
                        <ListEmptyState
                            title="No people in this date range"
                            description="Pick a wider date range to see more people."
                        />
                    }
                    emptyFilteredState={
                        <ListEmptyState
                            title="No people match"
                            description="Change or clear the filters to see more people."
                            action={{
                                label: 'Clear filters',
                                onClick: clearFilters,
                                'data-attr': `${DATA_ATTR}-clear-filters`,
                            }}
                        />
                    }
                    errorState={
                        <ListErrorState
                            title="Couldn't load people"
                            description="Try again. If it keeps happening, contact support."
                            retry={{ onClick: reload, 'data-attr': `${DATA_ATTR}-retry` }}
                        />
                    }
                    data-attr={DATA_ATTR}
                />
            )}
        </div>
    )
}
