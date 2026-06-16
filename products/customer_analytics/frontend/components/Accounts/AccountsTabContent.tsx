import { BindLogic, useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY } from '../../constants'
import { AccountsColumnConfigurator } from './AccountsColumnConfigurator'
import { AccountsHogQLTable } from './AccountsHogQLTable'
import { accountsLogic } from './accountsLogic'
import { AccountsMaxTools } from './AccountsMaxTools'
import { AccountsOverviewTiles } from './AccountsOverviewTiles'
import { AccountsOverviewTilesButton } from './AccountsOverviewTilesButton'
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
                <AccountsMaxTools />
                <AccountsTabFilters />
                <div className="flex justify-end gap-2">
                    <AccountsOverviewTilesButton />
                    <AccountsColumnConfigurator />
                </div>
                <AccountsOverviewTiles />
                <AccountsHogQLTable />
            </div>
        </BindLogic>
    )
}
