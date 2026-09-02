import { useActions, useValues } from 'kea'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    ActorsQuery,
    DataNode,
    EventsQuery,
    HogQLQuery,
    SessionsQuery,
    TracesQuery,
} from '~/queries/schema/schema-general'
import { isActorsQuery, isEventsQuery, isHogQLQuery, isSessionsQuery, isTracesQuery } from '~/queries/utils'

interface TestAccountFiltersProps {
    query: DataNode
    setQuery?: (query: ActorsQuery | EventsQuery | HogQLQuery | SessionsQuery | TracesQuery) => void
}
export function TestAccountFilters({ query, setQuery }: TestAccountFiltersProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    // A source-less ActorsQuery is the persons list, which carries its own filterTestAccounts flag
    // (like EventsQuery). Actors queries with an insight source use the source query's toggle instead.
    const isSourcelessActorsQuery = isActorsQuery(query) && !query.source

    if (
        !isEventsQuery(query) &&
        !isHogQLQuery(query) &&
        !isSessionsQuery(query) &&
        !isTracesQuery(query) &&
        !isSourcelessActorsQuery
    ) {
        return null
    }
    const checked = hasFilters
        ? !!(isHogQLQuery(query)
              ? query.filters?.filterTestAccounts
              : isEventsQuery(query) || isSessionsQuery(query) || isTracesQuery(query) || isSourcelessActorsQuery
                ? query.filterTestAccounts
                : false)
        : false
    const onChange = isHogQLQuery(query)
        ? (checked: boolean) => {
              const newQuery: HogQLQuery = {
                  ...query,
                  filters: {
                      ...query.filters,
                      filterTestAccounts: checked,
                  },
              }
              setQuery?.(newQuery)
          }
        : isEventsQuery(query) || isSessionsQuery(query) || isTracesQuery(query) || isSourcelessActorsQuery
          ? (checked: boolean) => {
                const newQuery: ActorsQuery | EventsQuery | SessionsQuery | TracesQuery = {
                    ...query,
                    filterTestAccounts: checked,
                }
                setQuery?.(newQuery)
            }
          : undefined

    return (
        <TestAccountFilterSwitch
            checked={checked}
            onChange={(checked: boolean) => {
                onChange?.(checked)
                setLocalDefault(checked)
            }}
            // The persons list is a person-level query: only person and cohort test filters apply.
            applicableFilterTypes={isSourcelessActorsQuery ? ['person', 'cohort'] : undefined}
        />
    )
}
