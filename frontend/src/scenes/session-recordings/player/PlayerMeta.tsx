import './PlayerMeta.scss'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTabs, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Logo } from '~/toolbar/assets/Logo'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

function WindowTab({
    title,
    url,
    windowIndex,
    active,
}: {
    title: string | null
    url: string | undefined
    windowIndex: number
    active: boolean
}): JSX.Element | null {
    const displayTitle = title || url || `Window ${windowIndex}`
    const copyableContent = url || title

    let isValidUrl = false
    try {
        new URL(copyableContent || '')
        isValidUrl = true
    } catch (_e) {
        // no valid url
    }

    return (
        <div className="px-2">
            <Tooltip title={url}>
                <span>{displayTitle}</span>
            </Tooltip>
            {active && copyableContent && (
                <>
                    {isValidUrl && (
                        <LemonButton
                            icon={<IconExternal />}
                            tooltip={copyableContent}
                            to={copyableContent}
                            targetBlank
                        />
                    )}
                    <CopyToClipboardInline
                        description={copyableContent}
                        explicitValue={copyableContent}
                        iconStyle={{ color: 'var(--muted-alt)' }}
                        selectable={true}
                        tooltipMessage="Copy URL"
                    />
                </>
            )}
            {isValidUrl && active && url && (
                <>
                    <LemonButton icon={<IconExternal />} tooltip={url} to={url} targetBlank />
                    <CopyToClipboardInline
                        description={url}
                        explicitValue={url}
                        iconStyle={{ color: 'var(--muted-alt)' }}
                        selectable={true}
                        tooltipMessage="Copy URL"
                    />
                </>
            )}
        </div>
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
    const { logicProps, isFullScreen, windowTitles } = useValues(sessionRecordingPlayerLogic)

    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))
    const { windowIds, trackedWindow, currentSegment, sessionPlayerMetaDataLoading, lastUrls, latestScreenTitle } =
        useValues(playerMetaLogic(logicProps))

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

    const currentWindow = currentSegment?.windowId
    const activeWindowId = trackedWindow || currentWindow

    return (
        <DraggableToNotebook href={urls.replaySingle(logicProps.sessionRecordingId)} onlyWithModifierKey>
            <div className={clsx('PlayerMeta', { 'PlayerMeta--fullscreen': isFullScreen })}>
                <div className="flex">
                    {sessionPlayerMetaDataLoading || !currentSegment ? (
                        <LemonSkeleton className="w-1/3 h-4 my-1" />
                    ) : (
                        activeWindowId && (
                            <>
                                <div>
                                    <LemonTabs
                                        size="small"
                                        tabs={windowIds.map((windowId, index) => ({
                                            key: windowId,
                                            label: (
                                                <WindowTab
                                                    title={latestScreenTitle || windowTitles[windowId]}
                                                    url={lastUrls[windowId]}
                                                    active={activeWindowId === windowId}
                                                    windowIndex={index + 1}
                                                />
                                            ),
                                        }))}
                                        activeKey={activeWindowId}
                                        onChange={(windowId) => setTrackedWindow(windowId)}
                                        barClassName="mb-0"
                                    />
                                </div>
                                <div className="flex flex-1 border-b justify-end px-2">
                                    {windowIds.length > 1 && (
                                        <LemonSwitch
                                            label="Follow the user"
                                            checked={trackedWindow === null}
                                            onChange={() =>
                                                trackedWindow
                                                    ? setTrackedWindow(null)
                                                    : setTrackedWindow(currentWindow as string)
                                            }
                                            disabledReason={!activeWindowId && 'There is no active window'}
                                        />
                                    )}
                                </div>
                            </>
                        )
                    )}
                </div>
                <PlayerWarningsRow />
            </div>
        </DraggableToNotebook>
    )
}
