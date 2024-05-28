import { useActions, useValues } from 'kea'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { TestAccountFilterSwitch } from 'scenes/settings/project/TestAccountFiltersConfig'
import { teamLogic } from 'scenes/teamLogic'

import { InsightQueryNode } from '~/queries/schema'

type TestAccountFilterProps = {
    query: InsightQueryNode
    setQuery: (query: InsightQueryNode) => void
    disabledReason?: string
}

export function InsightTestAccountFilter({
    query,
    setQuery,
    disabledReason,
}: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <TestAccountFilterSwitch
            checked={hasFilters ? !!query.filterTestAccounts : false}
            onChange={(checked: boolean) => {
                setQuery({ ...query, filterTestAccounts: checked })
                setLocalDefault(checked)
            }}
            disabledReason={disabledReason}
            fullWidth
        />
    )
}
