import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonWithPopup, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { openPlayerAddToPlaylistDialog } from 'scenes/session-recordings/player/add-to-playlist/PlayerAddToPlaylist'
import { IconLink, IconOpenInNew, IconPlus, IconSave, IconWithCount } from 'lib/components/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { LemonCheckbox, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { Popup } from 'lib/components/Popup/Popup'
import { useState } from 'react'

export function PlayerHeader({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const [showPlaylistPopup, setShowPlaylistPopup] = useState(false)
    const { recordingStartTime, sessionPlayerData } = useValues(logic)
    const { setPause } = useActions(logic)
    const playlists = sessionPlayerData.metadata.playlists ?? []

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    const onAddToPlaylist = (): void => {
        setPause()
        openPlayerAddToPlaylistDialog({
            sessionRecordingId,
            playerKey,
            recordingStartTime,
        })
    }

    return (
        <div className="py-2 px-3 flex flex-row justify-end gap-3">
            <LemonButton icon={<IconLink />} status="primary-alt" onClick={() => onShare()} tooltip="Share recording">
                Share
            </LemonButton>

            <Popup
                visible={showPlaylistPopup}
                onClickOutside={() => setShowPlaylistPopup(false)}
                overlay={
                    <div className="space-y-1">
                        <LemonInput type="search" placeholder="Search playlists..." />
                        <LemonButton fullWidth icon={<IconPlus />}>
                            New list
                        </LemonButton>

                        <div className="flex items-center gap-1">
                            <LemonButton icon={<LemonCheckbox checked />}>My great playlist</LemonButton>

                            <LemonButton icon={<IconOpenInNew />} />
                        </div>

                        <div className="flex items-center gap-1">
                            <LemonButton icon={<LemonCheckbox />}>Other playlist</LemonButton>

                            <LemonButton icon={<IconOpenInNew />} />
                        </div>
                    </div>
                }
            >
                <LemonButton
                    status="primary-alt"
                    data-attr="export-button"
                    sideIcon={<IconPlus />}
                    active={showPlaylistPopup}
                    onClick={() => setShowPlaylistPopup(!showPlaylistPopup)}
                >
                    Add to list
                </LemonButton>
            </Popup>
        </div>
    )
}
