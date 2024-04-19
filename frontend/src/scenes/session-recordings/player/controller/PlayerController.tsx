import {
    IconDownload,
    IconEllipsis,
    IconFastForward,
    IconMagic,
    IconPause,
    IconPlay,
    IconSearch,
    IconTrash,
} from '@posthog/icons'
import { LemonDialog, LemonMenu, LemonMenuItems, LemonSwitch } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFullScreen } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { PlayerMetaLinks } from '../PlayerMetaLinks'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

export function PlayerController({ size }: { size: 'small' | 'medium' }): JSX.Element {
    const { playingState, isFullScreen, sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)

    const { speed, skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSpeed, setSkipInactivitySetting } = useActions(playerSettingsLogic)

    const showPause = playingState === SessionPlayerState.PLAY
    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

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
                    </div>
                </div>

                {sessionRecordingId && (
                    <div className="flex items-center gap-0.5">
                        <PlayerMetaLinks iconsOnly={size === 'small'} />
                        {mode === SessionRecordingPlayerMode.Standard && <MenuActions />}
                    </div>
                )}
            </div>
        </div>
    )
}

const MenuActions = (): JSX.Element => {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { exportRecordingToFile, openExplorer, deleteRecording, setIsFullScreen } =
        useActions(sessionRecordingPlayerLogic)
    const { fetchSimilarRecordings } = useActions(sessionRecordingDataLogic(logicProps))

    const hasMobileExport = useFeatureFlag('SESSION_REPLAY_EXPORT_MOBILE_DATA')
    const hasSimilarRecordings = useFeatureFlag('REPLAY_SIMILAR_RECORDINGS')

    const onDelete = (): void => {
        setIsFullScreen(false)
        LemonDialog.open({
            title: 'Delete recording',
            description: 'Are you sure you want to delete this recording? This cannot be undone.',
            secondaryButton: {
                children: 'Cancel',
            },
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: deleteRecording,
            },
        })
    }

    const items: LemonMenuItems = [
        {
            label: 'Export to file',
            onClick: exportRecordingToFile,
            icon: <IconDownload />,
            tooltip: 'Export recording to a file. This can be loaded later into PostHog for playback.',
        },
        {
            label: 'Explore DOM',
            onClick: openExplorer,
            icon: <IconSearch />,
        },
        hasMobileExport && {
            label: 'Export mobile replay to file',
            onClick: () => exportRecordingToFile(true),
            tooltip:
                'DEBUG ONLY - Export untransformed recording to a file. This can be loaded later into PostHog for playback.',
            icon: <IconDownload />,
        },
        hasSimilarRecordings && {
            label: 'Find similar recordings',
            onClick: fetchSimilarRecordings,
            icon: <IconMagic />,
            tooltip: 'DEBUG ONLY - Find similar recordings based on distance calculations via embeddings.',
        },
        logicProps.playerKey !== 'modal' && {
            label: 'Delete recording',
            status: 'danger',
            onClick: onDelete,
            icon: <IconTrash />,
        },
    ]

    return (
        <LemonMenu items={items}>
            <LemonButton size="small" icon={<IconEllipsis />} />
        </LemonMenu>
    )
}
