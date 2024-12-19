import './PlayerMeta.scss'

import { LemonSelect, LemonSelectOption, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { isObject, percentage } from 'lib/utils'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { PlayerMetaLinks } from 'scenes/session-recordings/player/PlayerMetaLinks'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Logo } from '~/toolbar/assets/Logo'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

function URLOrScreen({ lastUrl }: { lastUrl: string | undefined }): JSX.Element | null {
    if (isObject(lastUrl)) {
        if ('href' in lastUrl) {
            // regression protection, we saw a user whose site was sometimes sending the string-ified location object
            // this is a best-effort attempt to show the href in that case in that case
            lastUrl = lastUrl['href'] as string | undefined
        }
    }

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

export function PlayerMeta({ iconsOnly }: { iconsOnly: boolean }): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const {
        windowIds,
        trackedWindow,
        resolution,
        lastPageviewEvent,
        lastUrl,
        scale,
        currentWindowIndex,
        sessionPlayerMetaDataLoading,
    } = useValues(playerMetaLogic(logicProps))

    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))

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
                <div className="flex items-center justify-between gap-1 whitespace-nowrap overflow-hidden px-1 py-0.5 text-xs">
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
                    <PlayerMetaLinks iconsOnly={iconsOnly} />
                    {resolutionView}
                </div>
            </div>
        </DraggableToNotebook>
    )
}
