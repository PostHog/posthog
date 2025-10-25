import './PlayerMeta.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectOption, Link } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand/Logo'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { isObject } from 'lib/utils'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { PlayerMetaLinks } from 'scenes/session-recordings/player/player-meta/PlayerMetaLinks'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'

import { PlayerPersonMeta } from './PlayerPersonMeta'
import { playerMetaLogic } from './playerMetaLogic'

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
    } catch {
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
                        iconStyle={{ color: 'var(--color-text-secondary)' }}
                        selectable={true}
                        data-attr="player-meta-copy-url"
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

export type PlayerMetaBreakpoints = 'small' | 'normal'

export function PlayerMeta(): JSX.Element {
    const { isCinemaMode } = useValues(playerSettingsLogic)
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
                className={clsx('PlayerMeta relative', {
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
                                data-attr="player-meta-window-select"
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
                    {!isCinemaMode && <PlayerMetaLinks size={size} />}
                    <PlayerPersonMeta />
                </div>
            </div>
        </DraggableToNotebook>
    )
}
