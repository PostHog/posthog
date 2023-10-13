import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState } from '~/types'
import { Seekbar } from './Seekbar'
import { SeekSkip } from './PlayerControllerTime'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconExport, IconFullScreen, IconMagnifier, IconPause, IconPlay, IconSkipInactivity } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

export function PlayerController(): JSX.Element {
    const { playingState, logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause, exportRecordingToFile, openExplorer, setIsFullScreen } =
        useActions(sessionRecordingPlayerLogic)

    const { speed, skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSpeed, setSkipInactivitySetting } = useActions(playerSettingsLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const showPause = playingState === SessionPlayerState.PLAY

    return (
        <div className="bg-bg-light flex flex-col select-none">
            <Seekbar />
            <div className="flex justify-between items-center h-8 gap-2 m-2">
                <div className="flex-1" />
                <div className="flex items-center gap-1">
                    <SeekSkip direction="backward" />

                    <LemonButton
                        status="primary-alt"
                        size="small"
                        onClick={togglePlayPause}
                        tooltip={
                            <>
                                {showPause ? 'Pause' : 'Play'}
                                <KeyboardShortcut space />
                            </>
                        }
                    >
                        {showPause ? <IconPause className="text-2xl" /> : <IconPlay className="text-2xl" />}
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
                                className={clsx('text-2xl', skipInactivitySetting ? 'text-link' : 'text-primary-alt')}
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
                                className={clsx('text-2xl', isFullScreen ? 'text-link' : 'text-primary-alt')}
                            />
                        </LemonButton>
                    </Tooltip>

                    {mode === SessionRecordingPlayerMode.Standard && (
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

                                    <LemonButton
                                        status="stealth"
                                        onClick={() => openExplorer()}
                                        fullWidth
                                        sideIcon={<IconMagnifier />}
                                    >
                                        Explore DOM
                                    </LemonButton>
                                </>
                            }
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
