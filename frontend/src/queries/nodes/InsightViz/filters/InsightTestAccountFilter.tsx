import { useActions } from 'kea'

import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'

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
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    return (
        <TestAccountFilterSwitch
            checked={!!query.filterTestAccounts}
            onChange={(checked: boolean) => {
                setQuery({ ...query, filterTestAccounts: checked })
                setLocalDefault(checked)
            }}
            disabledReason={disabledReason}
        />
    )
}
