import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { IconLink, IconOpenInNew, IconPlus } from 'lib/components/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { LemonCheckbox, LemonInput } from '@posthog/lemon-ui'
import { Popup } from 'lib/components/Popup/Popup'
import { useState } from 'react'
import { playerSettingsLogic } from './playerSettingsLogic'

export function PlayerMetaLinks({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const [showPlaylistPopup, setShowPlaylistPopup] = useState(false)
    const { sessionPlayerData } = useValues(logic)
    const { setPause } = useActions(logic)
    const playlists = sessionPlayerData.metadata.playlists ?? []
    const { isFullScreen } = useValues(playerSettingsLogic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    return (
        <div className="flex flex-row justify-end gap-2">
            <LemonButton
                icon={<IconLink />}
                onClick={onShare}
                tooltip="Share recording"
                size={isFullScreen ? 'small' : 'medium'}
            >
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
                    data-attr="export-button"
                    sideIcon={<IconPlus />}
                    active={showPlaylistPopup}
                    onClick={() => setShowPlaylistPopup(!showPlaylistPopup)}
                    size={isFullScreen ? 'small' : 'medium'}
                >
                    Add to list
                </LemonButton>
            </Popup>
        </div>
    )
}
