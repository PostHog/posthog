import { IconDownload, IconMagic, IconPlay, IconSearch } from '@posthog/icons'
import { LemonMenu } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconFullScreen, IconPause, IconSkipInactivity } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
import { SeekSkip, Timestamp } from './PlayerControllerTime'
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
            <div className="flex justify-between h-8 gap-2 m-2 mt-1">
                <div className="flex divide-x gap-2">
                    <Timestamp />
                    <div className="flex pl-2 gap-1">
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
                    </div>
                    <div className="flex pl-2">
                        <LemonButton
                            data-attr="skip-inactivity"
                            size="small"
                            onClick={() => {
                                setSkipInactivitySetting(!skipInactivitySetting)
                            }}
                            icon={
                                <IconSkipInactivity
                                    className={clsx(
                                        'text-2xl',
                                        skipInactivitySetting ? 'text-primary-3000' : 'text-primary-alt'
                                    )}
                                    enabled={skipInactivitySetting}
                                />
                            }
                        >
                            <span className={skipInactivitySetting ? 'text-primary-3000' : 'text-primary-alt'}>
                                {skipInactivitySetting ? 'Skipping inactivity' : 'Skip inactivity'}
                            </span>
                        </LemonButton>
                    </div>
                </div>

                <div className="flex items-center gap-1">
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
                                        sideIcon={<IconDownload />}
                                        tooltip="Export recording to a file. This can be loaded later into PostHog for playback."
                                    >
                                        Export to file
                                    </LemonButton>

                                    <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_EXPORT_MOBILE_DATA} match={true}>
                                        <LemonButton
                                            onClick={() => exportRecordingToFile(true)}
                                            fullWidth
                                            sideIcon={<IconDownload />}
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

                                    <LemonButton onClick={() => openExplorer()} fullWidth sideIcon={<IconSearch />}>
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
