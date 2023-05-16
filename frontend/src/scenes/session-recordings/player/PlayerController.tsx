import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState } from '~/types'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekSkip } from 'scenes/session-recordings/player/PlayerControllerTime'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconExport, IconFullScreen, IconMagnifier, IconPause, IconPlay, IconSkipInactivity } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'
import { playerSettingsLogic } from './playerSettingsLogic'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { sessionRecordingAnnotationLogic } from 'scenes/session-recordings/player/sessionRecordingAnnotationsLogic'
// import EmojiPicker from 'emoji-picker-react'

export function PlayerController(): JSX.Element {
    const { currentPlayerState, currentPlayerTime, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause, exportRecordingToFile, openExplorer } = useActions(sessionRecordingPlayerLogic)

    const annotationsLogic = sessionRecordingAnnotationLogic(logicProps)
    const { annotate } = useActions(annotationsLogic)

    const { speed, skipInactivitySetting, isFullScreen } = useValues(playerSettingsLogic)
    const { setSpeed, setSkipInactivitySetting, setIsFullScreen } = useActions(playerSettingsLogic)

    return (
        <div className="p-3 bg-light flex flex-col select-none">
            <Seekbar />
            <div className="flex justify-between items-center h-8 gap-2">
                <div className="flex-1">
                    <div className={'flex flex-row gap-x-2'}>
                        <LemonButton
                            status="stealth"
                            size="small"
                            icon={<>👍</>}
                            onClick={() => annotate({ content: '👍', timestamp: currentPlayerTime })}
                        />
                        <LemonButton
                            status="stealth"
                            size="small"
                            icon={<>👎</>}
                            onClick={() => annotate({ content: '👎', timestamp: currentPlayerTime })}
                        />
                        <LemonButton
                            status="stealth"
                            size="small"
                            icon={<>😍</>}
                            onClick={() => annotate({ content: '😍', timestamp: currentPlayerTime })}
                        />
                        <LemonButton
                            status="stealth"
                            size="small"
                            icon={<>🔥</>}
                            onClick={() => annotate({ content: '🔥', timestamp: currentPlayerTime })}
                        />
                        {/*<EmojiPicker />*/}
                    </div>
                </div>
                <div className="flex items-center gap-1">
                    <SeekSkip direction="backward" />
                    <LemonButton status="primary-alt" size="small" onClick={togglePlayPause}>
                        {[SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                            <IconPause className="text-2xl" />
                        ) : (
                            <IconPlay className="text-2xl" />
                        )}
                    </LemonButton>
                    <SeekSkip direction="forward" />
                </div>
                <div className="flex items-center gap-1 flex-1 justify-end">
                    <Tooltip title={'Playback speed'}>
                        <LemonButtonWithDropdown
                            data-attr="session-recording-speed-select"
                            dropdown={{
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
                        </LemonButtonWithDropdown>
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
                                    onClick={() => exportRecordingToFile()}
                                    fullWidth
                                    sideIcon={<IconExport />}
                                    tooltip="Export recording to a file. This can be loaded later into PostHog for playback."
                                >
                                    Export to file
                                </LemonButton>

                                <FlaggedFeature flag={FEATURE_FLAGS.RECORDINGS_DOM_EXPLORER} match={true}>
                                    <LemonButton
                                        status="stealth"
                                        onClick={() => openExplorer()}
                                        fullWidth
                                        sideIcon={<IconMagnifier />}
                                    >
                                        Explore DOM
                                    </LemonButton>
                                </FlaggedFeature>
                            </>
                        }
                    />
                </div>
            </div>
        </div>
    )
}
