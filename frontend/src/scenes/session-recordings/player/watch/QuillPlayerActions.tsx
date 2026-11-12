import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { usePlayerChromeMenuItems } from 'scenes/session-recordings/player/player-meta/PlayerMetaTopSettings'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { userLogic } from 'scenes/userLogic'

import { QuillInsertInNotebookPlaylistButton } from './QuillInsertInNotebookPlaylistButton'
import { QuillInspectDOM } from './QuillInspectDOM'
import { QuillPlayerActionsMenu } from './QuillPlayerActionsMenu'
import { QuillPlayerShareMenu } from './QuillPlayerShareMenu'
import { QuillSetPlaybackSpeed } from './QuillSetPlaybackSpeed'
import { QuillWindowSelect } from './QuillWindowSelect'
import { useDebugReplayMenuItems } from './useDebugReplayMenuItems'

export function QuillPlayerActions({
    size = 'normal',
    withWindowSelect = false,
    filled = false,
}: {
    size?: 'small' | 'normal'
    withWindowSelect?: boolean
    filled?: boolean
}): JSX.Element {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { debugMode } = useValues(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const chromeItems = usePlayerChromeMenuItems()
    const debugReplay = useDebugReplayMenuItems(
        debugMode &&
            !!(featureFlags[FEATURE_FLAGS.REPLAY_DEBUG_WITH_AI] || user?.is_impersonated) &&
            logicProps.playerKey !== 'modal'
    )

    return (
        <div className={filled ? 'flex items-center gap-2 flex-wrap' : 'flex items-center gap-0.5'}>
            {withWindowSelect && <QuillWindowSelect filled={filled} />}
            <QuillSetPlaybackSpeed filled={filled} />
            {debugMode && <QuillInspectDOM filled={filled} />}
            <QuillInsertInNotebookPlaylistButton size={size} />
            <QuillPlayerShareMenu filled={filled} />
            {sessionRecordingId && (
                <QuillPlayerActionsMenu filled={filled} extraItems={[...debugReplay.items, ...chromeItems]} />
            )}
            {debugReplay.modal}
        </div>
    )
}
