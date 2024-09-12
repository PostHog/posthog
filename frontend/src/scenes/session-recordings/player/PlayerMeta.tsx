import './PlayerMeta.scss'

import { LemonBanner, LemonSelect, LemonSelectOption, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Logo } from '~/toolbar/assets/Logo'

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

function PlayerWarningsRow(): JSX.Element | null {
    const { messageTooLargeWarnings } = useValues(sessionRecordingPlayerLogic)

    return messageTooLargeWarnings.length ? (
        <div>
            <LemonBanner
                type="error"
                action={{
                    children: 'Learn more',
                    to: 'https://posthog.com/docs/session-replay/troubleshooting#message-too-large-warning',
                    targetBlank: true,
                }}
            >
                This session recording had recording data that was too large and could not be captured. This will mean
                playback is not 100% accurate.{' '}
            </LemonBanner>
        </div>
    ) : null
}

export function PlayerMeta(): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const { windowIds, trackedWindow, lastPageviewEvent, lastUrl, currentWindowIndex, sessionPlayerMetaDataLoading } =
        useValues(playerMetaLogic(logicProps))

    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))

    const { ref, size } = useResizeBreakpoints({
        0: 'compact',
        550: 'normal',
    })

    const isSmallPlayer = size === 'compact'

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const whitelabel = getCurrentExporterData()?.whitelabel ?? false

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
                </div>
            </div>
        )
    }

    const windowOptions: LemonSelectOption<string | null>[] = [
        {
            label: <IconWindow value={currentWindowIndex} className="text-muted-alt" />,
            value: null,
            labelInMenu: <>Follow the user</>,
        },
    ]
    windowIds.forEach((windowId, index) => {
        windowOptions.push({
            label: <IconWindow value={index + 1} className="text-muted-alt" />,
            labelInMenu: (
                <div className="flex flex-row gap-2 space-between items-center">
                    Follow window: <IconWindow value={index + 1} className="text-muted-alt" />
                </div>
            ),
            value: windowId,
        })
    })

    return (
        <DraggableToNotebook href={urls.replaySingle(logicProps.sessionRecordingId)} onlyWithModifierKey>
            <div
                ref={ref}
                className={clsx('PlayerMeta', {
                    'PlayerMeta--fullscreen': isFullScreen,
                })}
            >
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
                            <LemonSelect
                                size="xsmall"
                                options={windowOptions}
                                value={trackedWindow}
                                disabledReason={windowIds.length <= 1 ? "There's only one window" : undefined}
                                onSelect={(value) => setTrackedWindow(value)}
                            />

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
                </div>
                <PlayerWarningsRow />
            </div>
        </DraggableToNotebook>
    )
}
