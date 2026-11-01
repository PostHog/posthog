import { useActions, useValues } from 'kea'

import { DropdownMenuCheckboxItem, MenuEmpty, Spinner } from '@posthog/quill'

import { cohortsModel } from '~/models/cohortsModel'
import { PropertyFilterType } from '~/types'

import { filterBarLogic } from './filterBarLogic'
import { FilterBarItem } from './filterBarTypes'

/** The project's cohorts, narrowed by the search field. One is the filter's value. */
export function FilterBarCohortValueItems({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { allCohorts, allCohortsLoading } = useValues(cohortsModel)
    const { setItemCohort } = useActions(filterBarLogic)
    const typed = query.trim().toLowerCase()
    const cohorts = allCohorts.results.filter(
        (cohort) => !cohort.deleted && (!typed || (cohort.name ?? '').toLowerCase().includes(typed))
    )
    const selectedId = item.filter.type === PropertyFilterType.Cohort ? item.filter.value : null

    return (
        <>
            {cohorts.map((cohort) => (
                <DropdownMenuCheckboxItem
                    key={cohort.id}
                    checked={selectedId === cohort.id}
                    closeOnClick
                    onCheckedChange={() => setItemCohort(item.id, cohort)}
                    data-attr="filter-bar-value"
                >
                    {cohort.name || `Cohort ${cohort.id}`}
                </DropdownMenuCheckboxItem>
            ))}
            {allCohortsLoading && cohorts.length === 0 && (
                <MenuEmpty>
                    <Spinner />
                    Loading cohorts…
                </MenuEmpty>
            )}
            {!allCohortsLoading && cohorts.length === 0 && (
                <MenuEmpty>{typed ? `No cohort matches "${query.trim()}"` : 'No cohorts yet'}</MenuEmpty>
            )}
        </>
    )
}
