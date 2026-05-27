import { useValues } from 'kea'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'

import { accountsLogic } from './accountsLogic'

export function AccountsHogQLTable(): JSX.Element {
    const { hogqlQuery } = useValues(accountsLogic)

    return (
        <DataTable
            uniqueKey="customer-analytics-accounts-hogql"
            query={hogqlQuery}
            setQuery={() => {
                // Filters are owned by accountsLogic; column/sort changes from the DataTable are ignored on purpose.
            }}
            readOnly
        />
    )
}
