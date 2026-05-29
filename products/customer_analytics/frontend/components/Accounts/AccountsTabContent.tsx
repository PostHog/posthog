import { BindLogic, useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { AccountsHogQLTable } from './AccountsHogQLTable'
import { ACCOUNTS_HOGQL_DATA_NODE_KEY, accountsLogic } from './accountsLogic'
import { AccountsOverviewTiles } from './AccountsOverviewTiles'
import { AccountsTabFilters } from './AccountsTabFilters'

export function AccountsTabContent(): JSX.Element {
    const { hogqlQuery } = useValues(accountsLogic)

    return (
        <BindLogic
            logic={dataNodeLogic}
            props={{
                key: ACCOUNTS_HOGQL_DATA_NODE_KEY,
                query: hogqlQuery.source,
            }}
        >
            <div className="flex flex-col gap-3">
                <AccountsTabFilters />
                <AccountsOverviewTiles />
                <AccountsHogQLTable />
            </div>
        </BindLogic>
    )
}
