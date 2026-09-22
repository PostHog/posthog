import { BindLogic, useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { ACCOUNTS_TABLE_DATA_NODE_KEY, ACCOUNTS_METRICS_DATA_NODE_KEY } from '../../constants'
import { accountsLogic } from './accountsLogic'
import { AccountsMaxTools } from './AccountsMaxTools'
import { AccountsOverviewTiles } from './AccountsOverviewTiles'
import { AccountsTabFilters } from './AccountsTabFilters'
import { AccountsTable } from './AccountsTable'

export function AccountsTabContent(): JSX.Element {
    const { accountsQuerySource, metricsQuery } = useValues(accountsLogic)

    return (
        <BindLogic
            logic={dataNodeLogic}
            props={{
                key: ACCOUNTS_TABLE_DATA_NODE_KEY,
                query: accountsQuerySource,
            }}
        >
            <div className="flex flex-col gap-3">
                <AccountsMaxTools />
                <AccountsTabFilters />
                <BindLogic
                    logic={dataNodeLogic}
                    props={{
                        key: ACCOUNTS_METRICS_DATA_NODE_KEY,
                        query: metricsQuery,
                    }}
                >
                    <AccountsOverviewTiles />
                </BindLogic>
                <AccountsTable />
            </div>
        </BindLogic>
    )
}
