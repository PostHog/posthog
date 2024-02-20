import { IconMagic } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconExport, IconFullScreen, IconMagnifier, IconPause, IconPlay, IconSkipInactivity } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { SeekSkip } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

export function PlayerController(): JSX.Element {
    const { playingState, logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause, exportRecordingToFile, openExplorer, setIsFullScreen } =
        useActions(sessionRecordingPlayerLogic)
    const { fetchSimilarRecordings } = useActions(sessionRecordingDataLogic(logicProps))

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
                    <Tooltip title="Playback speed">
                        <LemonButtonWithDropdown
                            data-attr="session-recording-speed-select"
                            dropdown={{
                                overlay: (
                                    <div className="space-y-px">
                                        {PLAYBACK_SPEEDS.map((speedToggle) => (
                                            <LemonButton
                                                fullWidth
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
                        >
                            {speed}x
                        </LemonButtonWithDropdown>
                    </Tooltip>

                    <Tooltip title={`Skip inactivity (${skipInactivitySetting ? 'on' : 'off'})`}>
                        <LemonButton
                            size="small"
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
                                        onClick={() => exportRecordingToFile()}
                                        fullWidth
                                        sideIcon={<IconExport />}
                                        tooltip="Export recording to a file. This can be loaded later into PostHog for playback."
                                    >
                                        Export to file
                                    </LemonButton>

                                    <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_EXPORT_MOBILE_DATA} match={true}>
                                        <LemonButton
                                            onClick={() => exportRecordingToFile(true)}
                                            fullWidth
                                            sideIcon={<IconExport />}
                                            tooltip="DEBUG ONLY - Export untransformed recording to a file. This can be loaded later into PostHog for playback."
                                        >
                                            DEBUG Export mobile replay to file DEBUG
                                        </LemonButton>
                                    </FlaggedFeature>

                                    <FlaggedFeature flag={FEATURE_FLAGS.REPLAY_SIMILAR_RECORDINGS} match={true}>
                                        <LemonButton
                                            onClick={() => fetchSimilarRecordings()}
                                            fullWidth
                                            sideIcon={<IconMagic />}
                                            tooltip="DEBUG ONLY - Find similar recordings based on distance calculations via embeddings."
                                        >
                                            Find similar recordings
                                        </LemonButton>
                                    </FlaggedFeature>

                                    <LemonButton onClick={() => openExplorer()} fullWidth sideIcon={<IconMagnifier />}>
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
