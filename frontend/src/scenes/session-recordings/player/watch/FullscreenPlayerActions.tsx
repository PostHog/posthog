import { useValues } from 'kea'

import { MenuActions } from 'scenes/session-recordings/player/player-meta/PlayerMetaLinks'
import {
    InspectDOM,
    SetPlaybackSpeed,
    usePlayerChromeMenuItems,
} from 'scenes/session-recordings/player/player-meta/PlayerMetaTopSettings'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerShareMenu } from 'scenes/session-recordings/player/share/PlayerShareMenu'
import { isFeedReplayLayout } from 'scenes/session-recordings/playlist/replayLayout'

export function FullscreenPlayerActions(): JSX.Element | null {
    const { logicProps, isFullScreen, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { replayLayout, debugMode } = useValues(playerSettingsLogic)
    const chromeItems = usePlayerChromeMenuItems()

    if (!isFullScreen || !logicProps.watchLayout || !isFeedReplayLayout(replayLayout)) {
        return null
    }

    return (
        <div className="relative h-0">
            <div
                {...{ theme: 'dark' }}
                className="absolute bottom-2 right-2 flex items-center gap-0.5 rounded-full bg-black/60 px-2 py-1 backdrop-blur-sm"
                data-attr="player-fullscreen-actions"
            >
                <SetPlaybackSpeed />
                {debugMode && <InspectDOM />}
                <PlayerShareMenu />
                {sessionRecordingId && <MenuActions size="normal" extraItems={chromeItems} />}
            </div>
        </div>
    )
}
