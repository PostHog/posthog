import { useActions, useValues } from 'kea'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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
        <LemonSwitch
            checked={checked}
            onChange={(checked: boolean) => {
                onChange?.(checked)
                setLocalDefault(checked)
            }}
            id="test-account-filter"
            bordered
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconSettings />}
                        to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                        size="small"
                        noPadding
                        className="ml-1"
                    />
                </div>
            }
            disabledReason={!hasFilters ? "You haven't set any internal and test filters" : null}
        />
    )
    return null
}
