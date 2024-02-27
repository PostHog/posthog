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
                },
                {
                    value: 'console_error_count',
                    label: 'Most console errors',
                },
                {
                    value: 'active_seconds',
                    label: 'Longest (active duration)',
                },
                {
                    value: 'duration',
                    label: 'Longest (total duration)',
                },
            ]}
        />
    )
}
