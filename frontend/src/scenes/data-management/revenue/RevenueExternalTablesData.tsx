import { useValues } from 'kea'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function RevenueExternalTablesData(): JSX.Element | null {
    // TODO: Add logic to get external tables data
    // Currently displaying the same as revenue events
    const { eventsQuery } = useValues(revenueEventsSettingsLogic)

    if (!eventsQuery) {
        return null
    }

    return (
        <div>
            <h3>Revenue external tables data</h3>
            <p>
                The following rows of data were imported from your revenue external tables. This is helpful when you're
                trying to debug what your revenue data looks like.
            </p>
            <h2>TODO</h2>
        </div>
    )
}
