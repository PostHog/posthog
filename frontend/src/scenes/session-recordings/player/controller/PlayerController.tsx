import { IconPause, IconPlay } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { PlayerMetaLinks } from '../PlayerMetaLinks'
import { PlayerSettings } from '../PlayerSettings'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

function SetPlaybackSpeed(): JSX.Element {
    const { speed } = useValues(sessionRecordingPlayerLogic)
    const { setSpeed } = useActions(sessionRecordingPlayerLogic)
    return (
        <LemonMenu
            data-attr="session-recording-speed-select"
            items={PLAYBACK_SPEEDS.map((speedToggle) => ({
                label: `${speedToggle}x`,
                onClick: () => setSpeed(speedToggle),
            }))}
        >
            <LemonButton size="small" tooltip="Playback speed" sideIcon={null}>
                {speed}x
            </LemonButton>
        </LemonMenu>
    )
}

function PlayPauseButton(): JSX.Element {
    const { playingState, endReached } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause } = useActions(sessionRecordingPlayerLogic)

    const showPause = playingState === SessionPlayerState.PLAY

    return (
        <LemonButton
            size="small"
            onClick={togglePlayPause}
            tooltip={
                <div className="flex gap-1">
                    <span>{showPause ? 'Pause' : endReached ? 'Restart' : 'Play'}</span>
                    <KeyboardShortcut space />
                </div>
            }
        >
            {showPause ? (
                <IconPause className="text-2xl" />
            ) : endReached ? (
                <IconSync className="text-2xl" />
            ) : (
                <IconPlay className="text-2xl" />
            )}
        </LemonButton>
    )
}

export function PlayerController({ iconsOnly }: { iconsOnly: boolean }): JSX.Element {
    return (
        <div className="bg-bg-light flex flex-col select-none">
            <Seekbar />
            <div className="flex justify-between h-8 gap-2 m-2 mt-1">
                <div className="flex gap-2">
                    <Timestamp />
                    <div className="flex gap-0.5">
                        <SeekSkip direction="backward" />
                        <PlayPauseButton />
                        <SeekSkip direction="forward" />
                        <SetPlaybackSpeed />
                        <PlayerSettings />
                    </div>
                </div>
                <PlayerMetaLinks iconsOnly={iconsOnly} />
            </div>
        </div>
    )
}
