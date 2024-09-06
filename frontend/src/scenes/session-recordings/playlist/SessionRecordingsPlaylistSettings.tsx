import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { playerSettingsLogic } from '../player/playerSettingsLogic'

export function SessionRecordingsPlaylistSettings(): JSX.Element {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)

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
        </div>
    )
}
