import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DurationTypeSelect } from 'scenes/session-recordings/filters/DurationTypeSelect'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { durationTypeToShow, hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setDurationTypeToShow, setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)

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
