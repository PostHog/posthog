import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function RevenueExampleExternalTablesData(): JSX.Element | null {
    const { exampleExternalDataSchemasQuery } = useValues(revenueEventsSettingsLogic)

    if (!exampleExternalDataSchemasQuery) {
        return null
    }

    return (
        <div>
            <h3>Revenue external tables data</h3>
            <p>
                The following rows of data were imported from your revenue external tables. This is helpful when you're
                trying to debug what your revenue data looks like.
            </p>
            <Query query={exampleExternalDataSchemasQuery} context={{ showOpenEditorButton: true }} />
        </div>
    )
}
