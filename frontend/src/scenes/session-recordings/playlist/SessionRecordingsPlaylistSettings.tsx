import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DurationTypeSelect } from 'scenes/session-recordings/filters/DurationTypeSelect'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { durationTypeToShow, hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setDurationTypeToShow, setHideViewedRecordings } = useActions(playerSettingsLogic)
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
                            value: 'active_seconds',
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
                            value: 'click_count',
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
                            tooltip: 'Highest click count',
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
            {orderBy === 'start_time' && (
                <div className="flex flex-row items-center justify-between space-x-2">
                    <span className="text-black font-medium">Show</span>
                    <DurationTypeSelect
                        value={durationTypeToShow}
                        onChange={(value) => setDurationTypeToShow(value)}
                        onChangeEventDescription="session recording list duration type to show selected"
                    />
                </div>
            )}
        </div>
    )
}
