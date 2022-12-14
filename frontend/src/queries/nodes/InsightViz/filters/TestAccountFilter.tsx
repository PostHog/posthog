import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { IconSettings } from 'lib/components/icons'
import { InsightQueryNode } from '~/queries/schema'

type TestAccountFilterProps = {
    query: InsightQueryNode
    setQuery: (query: InsightQueryNode) => void
}

export function TestAccountFilter({ query, setQuery }: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <LemonSwitch
            checked={hasFilters ? !!query.filterTestAccounts : false}
            onChange={(checked: boolean) => {
                localStorage.setItem('default_filter_test_accounts', checked.toString())
                setQuery({ ...query, filterTestAccounts: checked })
            }}
            id="test-account-filter"
            bordered
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconSettings />}
                        to="/project/settings#internal-users-filtering"
                        status="stealth"
                        size="small"
                        noPadding
                        className="ml-1"
                    />
                </div>
            }
            fullWidth
            disabled={!hasFilters}
        />
    )
}
