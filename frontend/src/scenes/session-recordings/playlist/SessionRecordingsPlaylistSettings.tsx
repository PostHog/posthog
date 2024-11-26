import { LemonSegmentedButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { PlaybackMode, playerSettingsLogic } from '../player/playerSettingsLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { hideViewedRecordings, playbackMode, autoplayDirection } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings, setPlaybackMode, setAutoplayDirection } = useActions(playerSettingsLogic)

    return (
        <div className="relative flex flex-col gap-2 p-3 border-b">
            <div className="flex justify-between items-center">
                <span className="text-black font-medium">Playback mode</span>
                <LemonSegmentedButton
                    value={playbackMode}
                    options={[
                        {
                            value: PlaybackMode.Recording,
                            label: 'Recordings',
                        },
                        {
                            value: PlaybackMode.Waterfall,
                            label: 'Waterfall',
                        },
                    ]}
                    onChange={setPlaybackMode}
                    size="xsmall"
                />
            </div>
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Hide viewed</span>
                <LemonSwitch
                    aria-label="Autoplay next recording"
                    checked={hideViewedRecordings}
                    onChange={() => setHideViewedRecordings(!hideViewedRecordings)}
                />
            </div>
            <div className="flex flex-row items-center justify-between space-x-2">
                <span className="text-black font-medium">Autoplay</span>

                <LemonSelect
                    tooltip={
                        <div className="text-center">
                            Autoplay next recording
                            <br />({autoplayDirection ? autoplayDirection : 'off'})
                        </div>
                    }
                    value={autoplayDirection}
                    aria-label="Autoplay next recording"
                    onChange={setAutoplayDirection}
                    dropdownPlacement="bottom-end"
                    dropdownMatchSelectWidth={false}
                    options={[
                        { value: null, label: 'Off' },
                        { value: 'newer', label: 'Newer recordings' },
                        { value: 'older', label: 'Older recordings' },
                    ]}
                    size="small"
                />
            </div>
        </div>
    )
}
