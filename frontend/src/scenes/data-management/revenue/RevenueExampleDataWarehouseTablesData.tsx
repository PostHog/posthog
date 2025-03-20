import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function RevenueExampleDataWarehouseTablesData(): JSX.Element | null {
    const { exampleDataWarehouseTablesQuery } = useValues(revenueEventsSettingsLogic)

    if (!exampleDataWarehouseTablesQuery) {
        return null
    }

    return (
        <div>
            <h3>Data warehouse tables revenue data</h3>
            <p>
                The following rows of data were imported from your data warehouse tables. This is helpful when you're
                trying to debug what your revenue data looks like.
            </p>
            <Query query={exampleDataWarehouseTablesQuery} context={{ showOpenEditorButton: true }} />
        </div>
    )
}
