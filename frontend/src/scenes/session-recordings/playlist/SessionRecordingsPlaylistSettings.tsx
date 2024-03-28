import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DurationTypeSelect } from 'scenes/session-recordings/filters/DurationTypeSelect'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { autoplayDirection, durationTypeToShow, hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setAutoplayDirection, setDurationTypeToShow, setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)

    return (
        <div className="relative flex flex-col gap-2 p-3 bg-side border-b">
            <Tooltip
                title={
                    <div className="text-center">
                        Autoplay next recording
                        <br />({!autoplayDirection ? 'off' : autoplayDirection})
                    </div>
                }
                placement="right"
            >
                <div className="flex flex-row items-center justify-between space-x-2">
                    <span className="text-black font-medium">Autoplay</span>

                    <LemonSelect
                        value={autoplayDirection}
                        aria-label="Autoplay next recording"
                        onChange={setAutoplayDirection}
                        dropdownMatchSelectWidth={false}
                        options={[
                            { value: null, label: 'off' },
                            { value: 'newer', label: 'newer recordings' },
                            { value: 'older', label: 'older recordings' },
                        ]}
                        size="small"
                    />
                </div>
            </Tooltip>
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
