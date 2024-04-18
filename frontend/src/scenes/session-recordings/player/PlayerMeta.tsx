import './PlayerMeta.scss'

import { IconEllipsis, IconTrash } from '@posthog/icons'
import { IconDownload, IconMagic, IconSearch } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonMenuItems, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Logo } from '~/toolbar/assets/Logo'

import { PlayerMetaLinks } from './PlayerMetaLinks'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

function URLOrScreen({ lastUrl }: { lastUrl: string | undefined }): JSX.Element | null {
    if (!lastUrl) {
        return null
    }

    // re-using the rrweb web schema means that this might be a mobile replay screen name
    let isValidUrl = false
    try {
        new URL(lastUrl || '')
        isValidUrl = true
    } catch (_e) {
        // no valid url
    }

    return (
        <span className="flex items-center gap-2 truncate">
            <span>·</span>
            <span className="flex items-center gap-1 truncate">
                {isValidUrl ? (
                    <Tooltip title="Click to open url">
                        <Link to={lastUrl} target="_blank" className="truncate">
                            {lastUrl}
                        </Link>
                    </Tooltip>
                ) : (
                    lastUrl
                )}
                <span className="flex items-center">
                    <CopyToClipboardInline
                        description={lastUrl}
                        explicitValue={lastUrl}
                        iconStyle={{ color: 'var(--muted-alt)' }}
                        selectable={true}
                    />
                </span>
            </span>
        </span>
    )
}

export function PlayerMeta(): JSX.Element {
    const { sessionRecordingId, logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const {
        sessionPerson,
        resolution,
        lastPageviewEvent,
        lastUrl,
        scale,
        currentWindowIndex,
        startTime,
        sessionPlayerMetaDataLoading,
    } = useValues(playerMetaLogic(logicProps))

    const { ref, size } = useResizeBreakpoints({
        0: 'compact',
        550: 'normal',
    })

    const isSmallPlayer = size === 'compact'

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const whitelabel = getCurrentExporterData()?.whitelabel ?? false

    const resolutionView = sessionPlayerMetaDataLoading ? (
        <LemonSkeleton className="w-1/3 h-4" />
    ) : resolution ? (
        <Tooltip
            placement="bottom"
            title={
                <>
                    The resolution of the page as it was captured was{' '}
                    <b>
                        {resolution.width} x {resolution.height}
                    </b>
                    <br />
                    You are viewing the replay at <b>{percentage(scale, 1, true)}</b> of the original size
                </>
            }
        >
            <span className="text-muted-alt text-xs">
                {resolution && (
                    <>
                        {resolution.width} x {resolution.height} {!isSmallPlayer && `(${percentage(scale, 1, true)})`}
                    </>
                )}
            </span>
        </Tooltip>
    ) : null

    if (mode === SessionRecordingPlayerMode.Sharing) {
        if (whitelabel) {
            return <></>
        }
        return (
            <div className="PlayerMeta">
                <div className="flex justify-between items-center m-2">
                    {!whitelabel ? (
                        <Tooltip title="Powered by PostHog" placement="right">
                            <Link to="https://posthog.com" className="flex items-center" target="blank">
                                <Logo />
                            </Link>
                        </Tooltip>
                    ) : null}
                    {resolutionView}
                </div>
            </div>
        )
    }

    return (
        <DraggableToNotebook href={urls.replaySingle(logicProps.sessionRecordingId)} onlyWithModifierKey>
            <div
                ref={ref}
                className={clsx('PlayerMeta', {
                    'PlayerMeta--fullscreen': isFullScreen,
                })}
            >
                <div
                    className={clsx(
                        'PlayerMeta__top flex items-center gap-1 shrink-0 p-2',
                        isFullScreen ? ' text-xs' : 'border-b'
                    )}
                >
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
                        <>
                            <PlayerMetaLinks />
                            {mode === SessionRecordingPlayerMode.Standard && <MenuActions />}
                        </>
                    )}
                </div>
                <div
                    className={clsx('flex items-center justify-between gap-2 whitespace-nowrap overflow-hidden', {
                        'p-2 h-10': !isFullScreen,
                        'p-1 px-3 text-xs h-12': isFullScreen,
                    })}
                >
                    {sessionPlayerMetaDataLoading ? (
                        <LemonSkeleton className="w-1/3 h-4 my-1" />
                    ) : (
                        <>
                            <Tooltip
                                title={
                                    <>
                                        Window {currentWindowIndex + 1}.
                                        <br />
                                        Each recording window translates to a distinct browser tab or window.
                                    </>
                                }
                            >
                                <span>
                                    <IconWindow value={currentWindowIndex + 1} className="text-muted-alt" />
                                </span>
                            </Tooltip>

                            <URLOrScreen lastUrl={lastUrl} />
                            {lastPageviewEvent?.properties?.['$screen_name'] && (
                                <span className="flex items-center gap-2 truncate">
                                    <span>·</span>
                                    <span className="flex items-center gap-1 truncate">
                                        {lastPageviewEvent?.properties['$screen_name']}
                                    </span>
                                </span>
                            )}
                        </>
                    )}
                    <div className={clsx('flex-1', isSmallPlayer ? 'min-w-[1rem]' : 'min-w-[5rem]')} />
                    {resolutionView}
                </div>
            </div>
        </DraggableToNotebook>
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
