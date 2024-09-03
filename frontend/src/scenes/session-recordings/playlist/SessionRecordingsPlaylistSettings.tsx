import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)
    const { setOrderBy } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <div className="relative flex flex-col gap-2 p-3 border-b">
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Hide viewed</span>
                <LemonSwitch
                    aria-label="Autoplay next recording"
                    checked={hideViewedRecordings}
                    onChange={() => setHideViewedRecordings(!hideViewedRecordings)}
                />
            </div>
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Order by</span>
                <LemonSelect
                    options={[
                        {
                            value: 'latest',
                            label: 'Latest',
                        },
                        {
                            value: 'earliest',
                            label: 'Earliest',
                        },
                        {
                            label: 'Longest',
                            tooltip: 'Active seconds',
                            options: [
                                {
                                    value: 'duration',
                                    label: 'Total duration',
                                },
                                {
                                    value: 'active_seconds',
                                    label: 'Active duration',
                                },
                                {
                                    value: 'inactive_seconds',
                                    label: 'Inactive duration',
                                },
                            ],
                        },
                        {
                            label: 'Most active',
                            options: [
                                {
                                    value: 'click_count',
                                    label: 'Clicks',
                                },
                                {
                                    value: 'keypress_count',
                                    label: 'Keypresses',
                                },
                                {
                                    value: 'mouse_activity_count',
                                    label: 'Mouse activity',
                                },
                            ],
                        },
                        {
                            value: 'console_error_count',
                            label: 'Most errors',
                        },
                    ]}
                    size="small"
                    value={orderBy}
                    onChange={setOrderBy}
                />
            </div>
        </div>
    )
}
