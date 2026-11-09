import '../player-meta/PlayerMeta.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    Button,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Tabs,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FEATURE_FLAGS } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { DebugReplayButton } from 'scenes/session-recordings/player/player-meta/DebugReplayButton'
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
import { userLogic } from 'scenes/userLogic'

import { SessionRecordingSidebarTab } from '~/types'

import { debugTabKeys } from './DebugTabBar'

type PlayerMode = 'watch' | 'debug'

// The select has no empty value, so "follow the user" takes a string of its own.
const FOLLOW_USER = 'follow'

export function PlayerModeBar(): JSX.Element {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { windowIds, trackedWindow, currentURL, currentWindowIndex, loading } = useValues(playerMetaLogic(logicProps))
    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))
    const { debugMode } = useValues(playerSettingsLogic)
    const { setDebugMode } = useActions(playerSettingsLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const chromeItems = usePlayerChromeMenuItems()
    const debugTabs = debugTabKeys(useLinkedIssuesAvailable())
    const { ref, size } = useResizeBreakpoints({ 0: 'small', 600: 'normal' })

    const mode: PlayerMode = debugMode ? 'debug' : 'watch'
    const showDebugReplayButton =
        (featureFlags[FEATURE_FLAGS.REPLAY_DEBUG_WITH_AI] || user?.is_impersonated) && logicProps.playerKey !== 'modal'
    const setMode = (next: PlayerMode): void => {
        posthog.capture('session recording mode changed', { mode: next })
        setDebugMode(next === 'debug')
        if (next === 'debug' && !debugTabs.includes(activeTab)) {
            setTab(SessionRecordingSidebarTab.INSPECTOR)
        }
    }

    const windowOptions = [
        { value: FOLLOW_USER, label: <IconWindow value={currentWindowIndex} className="text-muted-foreground" /> },
        ...windowIds.map((windowId) => ({
            value: String(windowId),
            label: <IconWindow value={windowId} className="text-muted-foreground" />,
        })),
    ]

    const { urlToUse, isWebUrl } = parseUrl(currentURL)

    return (
        <div ref={ref} data-quill className="PlayerMeta relative text-foreground">
            <div className="flex flex-row items-center gap-x-1 whitespace-nowrap overflow-hidden px-1 py-0.5 text-xs">
                <Tabs value={mode} onValueChange={(value) => setMode(value as PlayerMode)} className="shrink-0">
                    <TabsList className="h-7 [--quill-tabs-active-bg:var(--primary)]">
                        <TabsTrigger
                            value="watch"
                            className="text-xs data-active:text-(--primary-foreground)"
                            data-attr="player-mode-watch"
                        >
                            Watch
                        </TabsTrigger>
                        <TabsTrigger
                            value="debug"
                            className="text-xs data-active:text-(--primary-foreground)"
                            data-attr="player-mode-debug"
                        >
                            Debug
                        </TabsTrigger>
                    </TabsList>
                </Tabs>
                {loading ? (
                    <Skeleton className="w-1/3 h-4 my-1" />
                ) : (
                    <>
                        {windowIds.length > 1 && (
                            <Select
                                items={windowOptions}
                                value={trackedWindow === null ? FOLLOW_USER : String(trackedWindow)}
                                onValueChange={(value: string | null) =>
                                    setTrackedWindow(value === null || value === FOLLOW_USER ? null : Number(value))
                                }
                            >
                                <SelectTrigger
                                    render={<Button variant="outline" size="sm" />}
                                    data-attr="player-meta-window-select"
                                >
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value={FOLLOW_USER}>Follow the user</SelectItem>
                                    {windowIds.map((windowId) => (
                                        <SelectItem key={windowId} value={String(windowId)}>
                                            <span className="flex flex-row gap-x-1 items-center">
                                                Follow window:&nbsp;
                                                <IconWindow value={windowId} className="text-muted-foreground" />
                                            </span>
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
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
                                    <Button
                                        variant="link-muted"
                                        size="inline"
                                        render={<LinkPrimitive to={urlToUse} target="_blank" />}
                                        tooltip={`Click to open url: ${urlToUse}`}
                                        className="truncate"
                                        data-attr="player-meta-open-url"
                                    >
                                        {urlToUse}
                                    </Button>
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
                    {debugMode && showDebugReplayButton && <DebugReplayButton settingsBar />}
                    <InsertInNotebookPlaylistButton size={size} />
                    <PlayerShareMenu />
                </div>
            </div>
        </div>
    )
}
