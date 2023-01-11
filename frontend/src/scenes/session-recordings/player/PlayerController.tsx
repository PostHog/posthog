import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState } from '~/types'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekSkip } from 'scenes/session-recordings/player/PlayerControllerTime'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconExport, IconFullScreen, IconPause, IconPlay, IconSkipInactivity } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import clsx from 'clsx'
import { playerSettingsLogic } from './playerSettingsLogic'
import { More } from 'lib/components/LemonButton/More'
import { LemonCheckbox } from '@posthog/lemon-ui'

export function PlayerController({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const { togglePlayPause, exportRecordingToFile } = useActions(logic)
    const { currentPlayerState } = useValues(logic)

    const { speed, skipInactivitySetting, isFullScreen, autoplayEnabled } = useValues(playerSettingsLogic)
    const { setSpeed, setSkipInactivitySetting, setIsFullScreen, setAutoplayEnabled } = useActions(playerSettingsLogic)

    return (
        <div className="p-3 bg-light flex flex-col select-none">
            <Seekbar sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            <div className="flex justify-between items-center h-8 gap-2">
                <div className="flex-1" />
                <div className="flex items-center gap-1">
                    <SeekSkip sessionRecordingId={sessionRecordingId} playerKey={playerKey} direction="backward" />
                    <LemonButton status="primary-alt" size="small" onClick={togglePlayPause}>
                        {[SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                            <IconPause className="text-2xl" />
                        ) : (
                            <IconPlay className="text-2xl" />
                        )}
                    </LemonButton>
                    <SeekSkip sessionRecordingId={sessionRecordingId} playerKey={playerKey} direction="forward" />
                </div>
                <div className="flex items-center gap-1 flex-1 justify-end">
                    <Tooltip title={'Playback speed'}>
                        <LemonButtonWithPopup
                            data-attr="session-recording-speed-select"
                            popup={{
                                overlay: (
                                    <div className="space-y-px">
                                        {PLAYBACK_SPEEDS.map((speedToggle) => (
                                            <LemonButton
                                                fullWidth
                                                status="stealth"
                                                active={speed === speedToggle}
                                                key={speedToggle}
                                                onClick={() => {
                                                    setSpeed(speedToggle)
                                                }}
                                            >
                                                {speedToggle}x
                                            </LemonButton>
                                        ))}
                                    </div>
                                ),
                                closeOnClickInside: true,
                            }}
                            sideIcon={null}
                            size="small"
                            status="primary-alt"
                        >
                            {speed}x
                        </LemonButtonWithPopup>
                    </Tooltip>

                    <Tooltip title={`Skip inactivity (${skipInactivitySetting ? 'on' : 'off'})`}>
                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => {
                                setSkipInactivitySetting(!skipInactivitySetting)
                            }}
                        >
                            <IconSkipInactivity
                                className={clsx(
                                    'text-2xl',
                                    skipInactivitySetting ? 'text-primary' : 'text-primary-alt'
                                )}
                                enabled={skipInactivitySetting}
                            />
                        </LemonButton>
                    </Tooltip>
                    <Tooltip title={`${!isFullScreen ? 'Go' : 'Exit'} full screen (F)`}>
                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => {
                                setIsFullScreen(!isFullScreen)
                            }}
                        >
                            <IconFullScreen
                                className={clsx('text-2xl', isFullScreen ? 'text-primary' : 'text-primary-alt')}
                            />
                        </LemonButton>
                    </Tooltip>

                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => setAutoplayEnabled(!autoplayEnabled)}
                                    fullWidth
                                    sideIcon={
                                        <LemonCheckbox className="pointer-events-none" checked={autoplayEnabled} />
                                    }
                                >
                                    Autoplay enabled
                                </LemonButton>

                                <LemonButton
                                    status="stealth"
                                    onClick={() => exportRecordingToFile()}
                                    fullWidth
                                    sideIcon={<IconExport />}
                                    tooltip="Export recording to a file. This can be loaded later into PostHog for playback."
                                >
                                    Export to file
                                </LemonButton>
                            </>
                        }
                    />
                </div>
            </div>
        </div>
    )
}
