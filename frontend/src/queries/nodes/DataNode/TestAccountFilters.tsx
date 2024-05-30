import { useActions, useValues } from 'kea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DataNode, EventsQuery, HogQLQuery } from '~/queries/schema'
import { isEventsQuery, isHogQLQuery } from '~/queries/utils'

interface TestAccountFiltersProps {
    query: DataNode
    setQuery?: (query: EventsQuery | HogQLQuery) => void
}
export function TestAccountFilters({ query, setQuery }: TestAccountFiltersProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    if (!isEventsQuery(query) && !isHogQLQuery(query)) {
        return null
    }
    const checked = hasFilters
        ? !!(isHogQLQuery(query)
              ? query.filters?.filterTestAccounts
              : isEventsQuery(query)
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
        : isEventsQuery(query)
        ? (checked: boolean) => {
              const newQuery: EventsQuery = {
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
