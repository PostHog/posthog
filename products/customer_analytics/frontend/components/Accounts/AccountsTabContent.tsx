import { BindLogic, useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY, ACCOUNTS_METRICS_DATA_NODE_KEY } from '../../constants'
import { AccountsHogQLTable } from './AccountsHogQLTable'
import { accountsLogic } from './accountsLogic'
import { AccountsMaxTools } from './AccountsMaxTools'
import { AccountsOverviewTiles } from './AccountsOverviewTiles'
import { AccountsTabFilters } from './AccountsTabFilters'

export function AccountsTabContent(): JSX.Element {
    const { accountsQuerySource, metricsQuery } = useValues(accountsLogic)

    return (
        <BindLogic
            logic={dataNodeLogic}
            props={{
                key: ACCOUNTS_HOGQL_DATA_NODE_KEY,
                query: accountsQuerySource,
            }}
        >
            <BindLogic
                logic={dataNodeLogic}
                props={{
                    key: ACCOUNTS_METRICS_DATA_NODE_KEY,
                    query: metricsQuery,
                }}
            >
                <div className="flex flex-col gap-3">
                    <AccountsMaxTools />
                    <AccountsTabFilters />
                    <AccountsOverviewTiles />
                    <AccountsHogQLTable />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
