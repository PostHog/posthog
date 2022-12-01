import { LemonCheckbox } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconPlus, IconOpenInNew } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Popup } from 'lib/components/Popup/Popup'
import { useState } from 'react'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'

export function PlaylistPopup({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const [showPlaylistPopup, setShowPlaylistPopup] = useState(false)
    const { isFullScreen } = useValues(playerSettingsLogic)
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const { sessionPlayerData } = useValues(logic)
    const playlists = sessionPlayerData.metadata.playlists ?? []

    return (
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
    )
}
