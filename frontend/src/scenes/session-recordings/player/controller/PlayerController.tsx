import { IconFastForward, IconPause, IconPlay } from '@posthog/icons'
import { LemonMenu, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconFullScreen, IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { PlayerMetaLinks } from '../PlayerMetaLinks'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

export function PlayerController({ linkIconsOnly }: { linkIconsOnly: boolean }): JSX.Element {
    const { playingState, isFullScreen, endReached } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)

    const { speed, skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSpeed, setSkipInactivitySetting } = useActions(playerSettingsLogic)

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
                        <LemonSwitch
                            data-attr="skip-inactivity"
                            checked={skipInactivitySetting}
                            onChange={setSkipInactivitySetting}
                            tooltip={skipInactivitySetting ? 'Skipping inactivity' : 'Skip inactivity'}
                            handleContent={
                                <IconFastForward
                                    className={clsx(
                                        'p-0.5',
                                        skipInactivitySetting ? 'text-primary-3000' : 'text-border-bold'
                                    )}
                                />
                            }
                        />
                    </div>
                    <div className="flex pl-2">
                        <Tooltip title={`${!isFullScreen ? 'Go' : 'Exit'} full screen (F)`}>
                            <LemonButton size="small" onClick={() => setIsFullScreen(!isFullScreen)}>
                                <IconFullScreen
                                    className={clsx('text-2xl', isFullScreen ? 'text-link' : 'text-primary-alt')}
                                />
                            </LemonButton>
                        </Tooltip>
                    </div>
                </div>

                <PlayerMetaLinks iconsOnly={linkIconsOnly} />
            </div>
        </div>
    )
}
