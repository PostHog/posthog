import './PlayerMeta.scss'

import { LemonSelect, LemonSelectOption, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { isObject } from 'lib/utils'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { PlayerMetaBottomSettings } from 'scenes/session-recordings/player/player-meta/PlayerMetaBottomSettings'
import { PlayerMetaLinks } from 'scenes/session-recordings/player/player-meta/PlayerMetaLinks'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Logo } from '~/toolbar/assets/Logo'

import { playerMetaLogic } from './playerMetaLogic'
import { PlayerPersonMeta } from './PlayerPersonMeta'

export function parseUrl(lastUrl: unknown): { urlToUse: string | undefined; isValidUrl: boolean } {
    let urlToUse: string | undefined = typeof lastUrl === 'string' ? lastUrl : undefined
    if (isObject(lastUrl)) {
        // regression protection, we saw a user whose site was sometimes sending the string-ified location object
        // this is a best-effort attempt to show the href in that case
        // we've also seen lastUrl arrive as the empty object
        const maybeHref = lastUrl?.href
        if (typeof maybeHref === 'string') {
            urlToUse = maybeHref
        }
    }

    if (!urlToUse || urlToUse.trim() === '') {
        return { urlToUse: undefined, isValidUrl: false }
    }

    let isValidUrl = false
    try {
        new URL(urlToUse)
        isValidUrl = true
    } catch (_e) {
        // no valid url
    }

    return { urlToUse, isValidUrl }
}

function URLOrScreen({ url }: { url: unknown }): JSX.Element | null {
    const { urlToUse, isValidUrl } = parseUrl(url)

    if (!urlToUse) {
        return null
    }

    return (
        <span className="flex flex-row items-center gap-x-1 truncate">
            <span className="flex flex-row items-center gap-x-1 truncate">
                <span className="flex items-center">
                    <CopyToClipboardInline
                        description={urlToUse}
                        explicitValue={urlToUse}
                        iconStyle={{ color: 'var(--text-secondary)' }}
                        selectable={true}
                    />
                </span>
                {isValidUrl ? (
                    <Tooltip title={`Click to open url: ${urlToUse}`}>
                        <Link to={urlToUse} target="_blank" className="truncate">
                            {urlToUse}
                        </Link>
                    </Tooltip>
                ) : (
                    urlToUse
                )}
            </span>
        </span>
    )
}

export function ResolutionView({ size }: { size?: PlayerMetaBreakpoints }): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)

    const { resolutionDisplay, scaleDisplay, loading } = useValues(playerMetaLogic(logicProps))

    return loading ? (
        <LemonSkeleton className="w-1/3 h-4" />
    ) : (
        <Tooltip
            placement="bottom"
            title={
                <>
                    The resolution of the page as it was captured was <b>{resolutionDisplay}</b>
                    <br />
                    You are viewing the replay at <b>{scaleDisplay}</b> of the original size
                </>
            }
        >
            <span className="text-secondary text-xs flex flex-row items-center gap-x-1">
                {size === 'normal' && <span>{resolutionDisplay}</span>}
                <span>({scaleDisplay})</span>
            </span>
        </Tooltip>
    )
}

export type PlayerMetaBreakpoints = 'small' | 'normal'

export function PlayerMeta(): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const { windowIds, trackedWindow, lastPageviewEvent, currentURL, currentWindowIndex, loading } = useValues(
        playerMetaLogic(logicProps)
    )

    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        600: 'normal',
    })

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
                    <ResolutionView />
                </div>
            </div>
        )
    }

    const windowOptions: LemonSelectOption<string | null>[] = [
        {
            label: <IconWindow value={currentWindowIndex} className="text-secondary" />,
            value: null,
            labelInMenu: <>Follow the user</>,
        },
    ]
    windowIds.forEach((windowId, index) => {
        windowOptions.push({
            label: <IconWindow value={index + 1} className="text-secondary" />,
            labelInMenu: (
                <div className="flex flex-row gap-x-1 space-between items-center">
                    Follow window:&nbsp;
                    <IconWindow value={index + 1} className="text-secondary" />
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
                <div className="flex flex-row items-center justify-between gap-x-1 whitespace-nowrap overflow-hidden px-1 py-0.5 text-xs">
                    {loading ? (
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

                            <URLOrScreen url={currentURL} />
                            {lastPageviewEvent?.properties?.['$screen_name'] && (
                                <span className="flex flex-row items-center gap-x-1 truncate">
                                    <span>·</span>
                                    <span className="flex flex-row items-center gap-x-1 truncate">
                                        {lastPageviewEvent?.properties['$screen_name']}
                                    </span>
                                </span>
                            )}
                        </>
                    )}
                    <div className={clsx('flex-1', size === 'small' ? 'min-w-[1rem]' : 'min-w-[5rem]')} />
                    <PlayerMetaLinks size={size} />
                    <ResolutionView size={size} />
                    <PlayerPersonMeta />
                </div>
                <PlayerMetaBottomSettings size={size} />
            </div>
        </DraggableToNotebook>
    )
}
