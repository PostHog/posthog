import { useActions, useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { accountUsersTableLogic } from './accountUsersTableLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'

interface AccountUsersTableProps extends AccountViewTileLogicProps {
    accountId: string
    embedded?: boolean
}

export function AccountUsersTable({ accountId, embedded = true, ...tileProps }: AccountUsersTableProps): JSX.Element {
    const logic = accountUsersTableLogic({ accountId, ...tileProps })
    const { query } = useValues(logic)
    const { setQuery } = useActions(logic)

    return (
        <Query
            uniqueKey={`account-users-${accountId}-${tileProps.instanceId ?? 'default'}`}
            query={{ ...query, embedded }}
            setQuery={setQuery}
            dataAttr="customer-analytics-account-users-table"
        />
    )
}
