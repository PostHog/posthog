import { useActions, useValues } from 'kea'
import { HTMLAttributes, useMemo } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'

import { AiObservabilityErrorsListView, type ErrorListItemApi } from '../../generated/api.schemas'
import { HomeRangeTooLong } from '../home/components/HomeRangeTooLong'
import { ListEmptyState } from '../lists/components/ListEmptyState'
import { ListErrorState } from '../lists/components/ListErrorState'
import { ListTable } from '../lists/components/ListTable'
import { ListToolbar } from '../lists/components/ListToolbar'
import { QuickFilterChips } from '../lists/components/QuickFilterChips'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { ErrorsSetupState } from './components/ErrorsSetupState'
import { errorsTableColumns } from './components/ErrorsTableColumns'
import { errorFirstSeenLogic } from './errorFirstSeenLogic'
import { errorNewCountLogic } from './errorNewCountLogic'
import { ERRORS_LIST_FILTERS, errorsListLogic } from './errorsListLogic'

// pinned: autocapture dashboards and tests select the list and its controls by this value and the suffixes built on it
const DATA_ATTR = 'errors-list'
const ROW_PROPS: HTMLAttributes<HTMLTableRowElement> & { 'data-attr': string } = { 'data-attr': `${DATA_ATTR}-row` }

export function ErrorsListHost(): JSX.Element {
    const {
        items,
        counts,
        state,
        refreshing,
        canShowPrevious,
        canShowNext,
        pageIndex,
        sortedBy,
        nothingCaptured,
        rangeTooLongDetail,
    } = useValues(errorsListLogic)
    const { setPageIndex, setOrder, reload } = useActions(errorsListLogic)
    const { firstSeen } = useValues(errorFirstSeenLogic)
    const { timezone } = useValues(teamLogic)
    const { newCountLoad } = useValues(errorNewCountLogic)
    const { filters, searchDraft } = useValues(listFiltersLogic(ERRORS_LIST_FILTERS))
    const { setPropertyFilters, setSearchDraft, toggleQuickFilter, clearFilters } = useActions(
        listFiltersLogic(ERRORS_LIST_FILTERS)
    )
    const { dateFrom, dateTo, filterTestAccounts } = useValues(shellScopeLogic)
    const { setDateRange, setFilterTestAccounts } = useActions(shellScopeLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const maxOccurrences = counts?.maxOccurrences ?? 0
    const columns = useMemo(
        () =>
            errorsTableColumns({
                maxOccurrences,
                order: sortedBy,
                onOrder: setOrder,
                firstSeen,
                timezone,
                'data-attr': DATA_ATTR,
            }),
        [maxOccurrences, sortedBy, setOrder, firstSeen, timezone]
    )

    return (
        <div className="flex flex-col gap-3">
            <QuickFilterChips
                chips={[
                    {
                        id: AiObservabilityErrorsListView.Increasing,
                        label: 'Increasing',
                        count: counts?.increasing ?? null,
                        tone: 'danger',
                    },
                    {
                        id: AiObservabilityErrorsListView.Decreasing,
                        label: 'Decreasing',
                        count: counts?.decreasing ?? null,
                    },
                    {
                        id: AiObservabilityErrorsListView.New,
                        label: 'New',
                        count: newCountLoad?.status === 'ready' ? newCountLoad.value : null,
                        countStatus: newCountLoad?.status,
                    },
                ]}
                active={filters.quickFilter}
                onToggle={toggleQuickFilter}
                data-attr={DATA_ATTR}
            />
            <ListToolbar
                search={searchDraft}
                onSearchChange={setSearchDraft}
                searchPlaceholder="Search error messages"
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
            <ListTable<ErrorListItemApi>
                state={state}
                columns={columns}
                rows={items}
                rowKey={(item) => item.key}
                refreshing={refreshing}
                onRow={() => ROW_PROPS}
                onPrevious={canShowPrevious ? () => setPageIndex(pageIndex - 1) : undefined}
                onNext={canShowNext ? () => setPageIndex(pageIndex + 1) : undefined}
                emptyState={
                    nothingCaptured ? (
                        <ErrorsSetupState tracesHref={urls.aiObservabilityTraces()} data-attr={DATA_ATTR} />
                    ) : (
                        <ListEmptyState
                            title="No errors in this date range"
                            description="Pick a wider date range to see older errors."
                        />
                    )
                }
                emptyFilteredState={
                    <ListEmptyState
                        title="No errors match"
                        description="Change or clear the filters to see more errors."
                        action={{
                            label: 'Clear filters',
                            onClick: clearFilters,
                            'data-attr': `${DATA_ATTR}-clear-filters`,
                        }}
                    />
                }
                errorState={
                    rangeTooLongDetail ? (
                        <HomeRangeTooLong detail={rangeTooLongDetail} />
                    ) : (
                        <ListErrorState
                            title="Could not load errors"
                            description="Try again. If it keeps happening, contact support."
                            retry={{ onClick: reload, 'data-attr': `${DATA_ATTR}-retry` }}
                        />
                    )
                }
                data-attr={DATA_ATTR}
            />
        </div>
    )
}
