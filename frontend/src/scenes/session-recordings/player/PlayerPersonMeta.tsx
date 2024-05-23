import './PlayerMeta.scss'

import { IconDownload, IconEllipsis, IconMagic, IconSearch, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'

import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

export function PlayerPersonMeta(): JSX.Element {
    const { sessionRecordingId, logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const { sessionPerson, startTime } = useValues(playerMetaLogic(logicProps))

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    return (
        <div
            className={clsx('PlayerMeta', {
                'PlayerMeta--fullscreen': isFullScreen,
            })}
        >
            <div className={clsx('PlayerMeta__top flex items-center gap-1 shrink-0', isFullScreen && ' text-xs')}>
                <div className="ph-no-capture">
                    {!sessionPerson ? (
                        <LemonSkeleton.Circle className="w-8 h-8" />
                    ) : (
                        <ProfilePicture name={asDisplay(sessionPerson)} />
                    )}
                </div>
                <div className="overflow-hidden ph-no-capture flex-1">
                    <div>
                        {!sessionPerson || !startTime ? (
                            <LemonSkeleton className="w-1/3 h-4 my-1" />
                        ) : (
                            <div className="flex gap-1">
                                <span className="font-bold whitespace-nowrap truncate">
                                    <PersonDisplay person={sessionPerson} withIcon={false} noEllipsis={true} />
                                </span>
                                ·
                                <TZLabel
                                    time={dayjs(startTime)}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                    showPopover={false}
                                />
                            </div>
                        )}
                    </div>
                </div>

                {sessionRecordingId && (
                    <div className="flex items-center gap-0.5">
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
            onClick: () => exportRecordingToFile(false),
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
            <LemonButton size="small" icon={<IconEllipsis className="rotate-90" />} />
        </LemonMenu>
    )
}
