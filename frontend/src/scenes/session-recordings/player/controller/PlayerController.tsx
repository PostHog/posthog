import { IconPause, IconPlay } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconFullScreen, IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { PlayerMetaLinks } from '../PlayerMetaLinks'
import { PlayerSettings } from '../PlayerSettings'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

export function PlayerController({ linkIconsOnly }: { linkIconsOnly: boolean }): JSX.Element {
    const { playingState, isFullScreen, endReached } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)

    const showPause = playingState === SessionPlayerState.PLAY

    return (
        <div className="bg-bg-light flex flex-col select-none">
            <Seekbar />
            <div className="flex justify-between h-8 gap-2 m-2 mt-1">
                <div className="flex divide-x gap-2">
                    <Timestamp />
                    <div className="flex pl-2 gap-1">
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
                        <SeekSkip direction="backward" />
                        <SeekSkip direction="forward" />
                        <LemonButton
                            size="small"
                            onClick={() => setIsFullScreen(!isFullScreen)}
                            tooltip={`${!isFullScreen ? 'Go' : 'Exit'} full screen (F)`}
                        >
                            <IconFullScreen
                                className={clsx('text-2xl', isFullScreen ? 'text-link' : 'text-primary-alt')}
                            />
                        </LemonButton>
                    </div>
                    <PlayerSettings />
                </div>

                <PlayerMetaLinks iconsOnly={linkIconsOnly} />
            </div>
        </div>
    )
}
