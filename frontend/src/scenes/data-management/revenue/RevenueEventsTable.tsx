import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function RevenueEventsTable(): JSX.Element | null {
    const { eventsQuery } = useValues(revenueEventsSettingsLogic)

    if (!eventsQuery) {
        return null
    }

    return (
        <div>
            <h3>Revenue events</h3>
            <p>
                The following revenue events are available in your data. This is helpful when you're trying to debug
                what your revenue events look like.
            </p>
            <Query query={eventsQuery} context={{ showOpenEditorButton: true }} />
        </div>
    )
}
