import '../player-meta/PlayerMeta.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSegmentedButton, LemonSelect, LemonSelectOption, Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { parseUrl } from 'scenes/session-recordings/player/player-meta/PlayerMeta'
import {
    InsertInNotebookPlaylistButton,
    MenuActions,
} from 'scenes/session-recordings/player/player-meta/PlayerMetaLinks'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import {
    InspectDOM,
    SetPlaybackSpeed,
    usePlayerChromeMenuItems,
} from 'scenes/session-recordings/player/player-meta/PlayerMetaTopSettings'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerShareMenu } from 'scenes/session-recordings/player/share/PlayerShareMenu'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'
import { useLinkedIssuesAvailable } from 'scenes/session-recordings/player/sidebar/useLinkedIssuesAvailable'

import { SessionRecordingSidebarTab } from '~/types'

import { debugTabKeys } from './DebugTabBar'

type PlayerMode = 'watch' | 'debug'

export function PlayerModeBar(): JSX.Element {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { windowIds, trackedWindow, currentURL, currentWindowIndex, loading } = useValues(playerMetaLogic(logicProps))
    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))
    const { debugMode } = useValues(playerSettingsLogic)
    const { setDebugMode } = useActions(playerSettingsLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const chromeItems = usePlayerChromeMenuItems()
    const debugTabs = debugTabKeys(useLinkedIssuesAvailable())
    const { ref, size } = useResizeBreakpoints({ 0: 'small', 600: 'normal' })

    const mode: PlayerMode = debugMode ? 'debug' : 'watch'
    const setMode = (next: PlayerMode): void => {
        posthog.capture('session recording mode changed', { mode: next })
        setDebugMode(next === 'debug')
        if (next === 'debug' && !debugTabs.includes(activeTab)) {
            setTab(SessionRecordingSidebarTab.INSPECTOR)
        }
    }

    const windowOptions: LemonSelectOption<number | null>[] = [
        {
            label: <IconWindow value={currentWindowIndex} className="text-secondary" />,
            value: null,
            labelInMenu: <>Follow the user</>,
        },
        ...windowIds.map((windowId) => ({
            label: <IconWindow value={windowId} className="text-secondary" />,
            labelInMenu: (
                <div className="flex flex-row gap-x-1 items-center">
                    Follow window:&nbsp;
                    <IconWindow value={windowId} className="text-secondary" />
                </div>
            ),
            value: windowId,
        })),
    ]
    const { urlToUse, isWebUrl } = parseUrl(currentURL)

    return (
        <div ref={ref} className="PlayerMeta relative">
            <div className="flex flex-row items-center gap-x-1 whitespace-nowrap overflow-hidden px-1 py-0.5 text-xs">
                <LemonSegmentedButton
                    size="xsmall"
                    value={mode}
                    onChange={setMode}
                    options={[
                        { value: 'watch', label: 'Watch', 'data-attr': 'player-mode-watch' },
                        { value: 'debug', label: 'Debug', 'data-attr': 'player-mode-debug' },
                    ]}
                />
                {loading ? (
                    <LemonSkeleton className="w-1/3 h-4 my-1" />
                ) : (
                    <>
                        {windowIds.length > 1 && (
                            <LemonSelect
                                size="xsmall"
                                options={windowOptions}
                                value={trackedWindow}
                                onSelect={(value) => setTrackedWindow(value)}
                                data-attr="player-meta-window-select"
                            />
                        )}
                        {urlToUse && (
                            <span className="flex items-center gap-x-1 truncate">
                                <CopyToClipboardInline
                                    description={urlToUse}
                                    explicitValue={urlToUse}
                                    iconStyle={{ color: 'var(--color-text-secondary)' }}
                                    selectable={true}
                                    data-attr="player-meta-copy-url"
                                />
                                {isWebUrl ? (
                                    <Tooltip title={`Click to open url: ${urlToUse}`}>
                                        <Link
                                            data-attr="player-meta-open-url"
                                            to={urlToUse}
                                            target="_blank"
                                            className="truncate"
                                        >
                                            {urlToUse}
                                        </Link>
                                    </Tooltip>
                                ) : (
                                    <span className="truncate">{urlToUse}</span>
                                )}
                            </span>
                        )}
                    </>
                )}
                <div className="flex-1 min-w-4" />
                <div className="flex items-center gap-0.5">
                    {sessionRecordingId && <MenuActions size={size} extraItems={chromeItems} />}
                    <SetPlaybackSpeed />
                    {debugMode && <InspectDOM />}
                    <InsertInNotebookPlaylistButton size={size} />
                    <PlayerShareMenu />
                </div>
            </div>
        </div>
    )
}
