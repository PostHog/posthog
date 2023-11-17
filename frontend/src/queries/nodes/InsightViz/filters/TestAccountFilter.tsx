import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { IconSettings } from 'lib/lemon-ui/icons'
import { InsightQueryNode } from '~/queries/schema'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { urls } from 'scenes/urls'

type TestAccountFilterProps = {
    query: InsightQueryNode
    setQuery: (query: InsightQueryNode) => void
}

export function TestAccountFilter({ query, setQuery }: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <LemonSwitch
            checked={hasFilters ? !!query.filterTestAccounts : false}
            onChange={(checked: boolean) => {
                setQuery({ ...query, filterTestAccounts: checked })
                setLocalDefault(checked)
            }}
            id="test-account-filter"
            bordered
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconSettings />}
                        to={urls.settings('project', 'internal-user-filtering')}
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
