import { useActions, useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { AccountsHogQLTable } from './AccountsHogQLTable'
import { accountsLogic, AccountsView } from './accountsLogic'
import { AccountsTabFilters } from './AccountsTabFilters'
import { AccountsTable } from './AccountsTable'

export function AccountsTabContent(): JSX.Element {
    const { activeView } = useValues(accountsLogic)
    const { setActiveView } = useActions(accountsLogic)

    return (
        <div className="flex flex-col gap-3">
            <AccountsTabFilters />
            <LemonTabs
                activeKey={activeView}
                onChange={(key) => setActiveView(key as AccountsView)}
                tabs={[
                    {
                        key: 'endpoint',
                        label: 'REST endpoint',
                        content: <AccountsTable />,
                    },
                    {
                        key: 'hogql',
                        label: 'HogQL query',
                        content: <AccountsHogQLTable />,
                    },
                ]}
            />
        </div>
    )
}
