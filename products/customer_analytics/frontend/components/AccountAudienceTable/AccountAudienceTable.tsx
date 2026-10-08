import { BindLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { AccountsQueryResponse, DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { accountsColumnConfigLogic } from '../Accounts/accountsColumnConfigLogic'
import { AccountAudienceTableFilters } from './AccountAudienceTableFilters'
import { AccountAudienceTableLogicProps, accountAudienceTableLogic } from './accountAudienceTableLogic'
import { useAccountAudienceTableColumns } from './useAccountAudienceTableColumns'

const ignoreDataTableQueryChange = (): void => {}

// Only mounted while a table filter is active, so an unfiltered table runs no extra count query.
function AccountAudienceMatchCount(): JSX.Element | null {
    const { countDataNodeKey, countQuery } = useValues(accountAudienceTableLogic)
    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic({ key: countDataNodeKey, query: countQuery })
    )
    const count = (response as AccountsQueryResponse | null)?.metricsResults?.[0]

    if (responseError) {
        return null
    }
    if (responseLoading || typeof count !== 'number') {
        return <LemonSkeleton className="h-4 w-40" />
    }
    return (
        <div className="text-secondary text-sm" data-attr="account-audience-match-count">
            {humanFriendlyNumber(count)} matching {count === 1 ? 'account' : 'accounts'}
        </div>
    )
}

function AccountAudienceMatchCountWhenFiltered(): JSX.Element | null {
    const { hasTableFilters } = useValues(accountAudienceTableLogic)
    return hasTableFilters ? <AccountAudienceMatchCount /> : null
}

function AccountAudienceDataTable(): JSX.Element {
    const { tableQuery, tableDataNodeKey } = useValues(accountAudienceTableLogic)
    const columns = useAccountAudienceTableColumns()
    const context = useMemo<QueryContext<DataTableNode>>(
        () => ({
            columns,
            dataNodeLogicKey: tableDataNodeKey,
            emptyStateHeading: 'No accounts match these filters',
            emptyStateDetail: 'Clear a filter to see more of this audience.',
        }),
        [columns, tableDataNodeKey]
    )

    if (!tableQuery) {
        return <LemonSkeleton repeat={5} className="h-8" />
    }
    return (
        <DataTable
            uniqueKey={tableDataNodeKey}
            query={tableQuery}
            setQuery={ignoreDataTableQueryChange}
            context={context}
            readOnly
        />
    )
}

export function AccountAudienceTable(props: AccountAudienceTableLogicProps): JSX.Element {
    return (
        <BindLogic logic={accountAudienceTableLogic} props={props}>
            <BindLogic logic={accountsColumnConfigLogic} props={{ scope: props.scope }}>
                <div className="flex flex-col gap-2 @container">
                    <AccountAudienceTableFilters />
                    <AccountAudienceMatchCountWhenFiltered />
                    <AccountAudienceDataTable />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
