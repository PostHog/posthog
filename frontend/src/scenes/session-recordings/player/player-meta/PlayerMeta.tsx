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

function URLOrScreen({ lastUrl }: { lastUrl: string | undefined }): JSX.Element | null {
    if (isObject(lastUrl) && 'href' in lastUrl) {
        // regression protection, we saw a user whose site was sometimes sending the string-ified location object
        // this is a best-effort attempt to show the href in that case
        lastUrl = lastUrl['href'] as string | undefined
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
        <span className="flex flex-row items-center space-x-1 truncate">
            <span>·</span>
            <span className="flex flex-row items-center space-x-1 truncate">
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
                        iconStyle={{ color: 'var(--text-secondary)' }}
                        selectable={true}
                    />
                </span>
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
            <span className="text-secondary text-xs flex flex-row items-center space-x-1">
                {size === 'normal' && <span>{resolutionDisplay}</span>}
                <span>({scaleDisplay})</span>
            </span>
        </Tooltip>
    )
}

export type PlayerMetaBreakpoints = 'small' | 'normal'

export function PlayerMeta(): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const { windowIds, trackedWindow, lastPageviewEvent, lastUrl, currentWindowIndex, loading } = useValues(
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
                <div className="flex flex-row space-x-1 space-between items-center">
                    Follow window: <IconWindow value={index + 1} className="text-secondary" />
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
                <div className="flex flex-row items-center justify-between space-x-1 whitespace-nowrap overflow-hidden px-1 py-0.5 text-xs">
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

                            <URLOrScreen lastUrl={lastUrl} />
                            {lastPageviewEvent?.properties?.['$screen_name'] && (
                                <span className="flex flex-row items-center space-x-1 truncate">
                                    <span>·</span>
                                    <span className="flex flex-row items-center space-x-1 truncate">
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
