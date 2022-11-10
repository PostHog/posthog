import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState, SessionRecordingPlayerProps } from '~/types'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekSkip, Timestamp } from 'scenes/session-recordings/player/PlayerControllerTime'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconFullScreen, IconPause, IconPlay, IconSkipInactivity, IconOpenInNew, IconLink } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import clsx from 'clsx'
import { PlayerInspectorPicker } from './PlayerInspector'
import { urls } from 'scenes/urls'
import { openPlayerShareDialog } from './share/PlayerShare'

interface PlayerControllerProps extends SessionRecordingPlayerProps {
    isDetail: boolean
    hideInspectorPicker?: boolean
}

export function PlayerController({
    sessionRecordingId,
    playerKey,
    isDetail,
    hideInspectorPicker = false,
}: PlayerControllerProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const { togglePlayPause, setSpeed, setSkipInactivitySetting, setIsFullScreen } = useActions(logic)
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting, isFullScreen, setPause } = useValues(logic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    return (
        <div className="p-3 bg-light flex flex-col select-none">
            <div className="flex items-center h-8 mb-2" data-attr="rrweb-controller">
                {!isSmallScreen && <Timestamp sessionRecordingId={sessionRecordingId} playerKey={playerKey} />}
                <Seekbar sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            <div className="flex justify-between items-center h-8 gap-2">
                <div className="flex items-center gap-2 flex-1">
                    {!hideInspectorPicker && !isFullScreen && (
                        <PlayerInspectorPicker sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                    )}
                </div>
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
                    {!isDetail && (
                        <Tooltip title={'Open in new tab (D)'}>
                            <LemonButton
                                size="small"
                                status="primary-alt"
                                to={urls.sessionRecording(sessionRecordingId)}
                                targetBlank
                            >
                                <IconOpenInNew className={'text-xl text-primary-alt'} />
                            </LemonButton>
                        </Tooltip>
                    )}
                    <Tooltip title={`Share recording`}>
                        <LemonButton size="small" status="primary-alt" onClick={() => onShare()}>
                            <IconLink
                                className={clsx('text-2xl', isFullScreen ? 'text-primary' : 'text-primary-alt')}
                            />
                        </LemonButton>
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}
