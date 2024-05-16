import { useActions, useValues } from 'kea'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'

export const OrderingFilters = (): JSX.Element => {
    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)
    const { setOrderBy } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <LemonRadio
            value={orderBy}
            onChange={setOrderBy}
            options={[
                {
                    value: 'start_time',
                    label: 'Latest',
                    'data-attr': 'session-replay-ordering-latest',
                },
                {
                    value: 'console_error_count',
                    label: 'Most console errors',
                    'data-attr': 'session-replay-ordering-errors',
                },
                {
                    value: 'active_seconds',
                    label: 'Longest (active duration)',
                    'data-attr': 'session-replay-ordering-active',
                },
                {
                    value: 'duration',
                    label: 'Longest (total duration)',
                    'data-attr': 'session-replay-ordering-duration',
                },
            ]}
        />
    )
}
