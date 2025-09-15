import { useActions, useValues } from 'kea'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DataNode, EventsQuery, HogQLQuery, TracesQuery } from '~/queries/schema/schema-general'
import { isEventsQuery, isHogQLQuery, isTracesQuery } from '~/queries/utils'

interface TestAccountFiltersProps {
    query: DataNode
    setQuery?: (query: EventsQuery | HogQLQuery | TracesQuery) => void
}
export function TestAccountFilters({ query, setQuery }: TestAccountFiltersProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    if (!isEventsQuery(query) && !isHogQLQuery(query) && !isTracesQuery(query)) {
        return null
    }
    const checked = hasFilters
        ? !!(isHogQLQuery(query)
              ? query.filters?.filterTestAccounts
              : isEventsQuery(query) || isTracesQuery(query)
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
        : isEventsQuery(query) || isTracesQuery(query)
          ? (checked: boolean) => {
                const newQuery: EventsQuery | TracesQuery = {
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
        />
    )
}
