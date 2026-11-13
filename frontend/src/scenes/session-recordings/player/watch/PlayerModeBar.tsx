import '../player-meta/PlayerMeta.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBug } from '@posthog/icons'
import { Button, Skeleton, Toggle } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { parseUrl } from 'scenes/session-recordings/player/player-meta/PlayerMeta'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'
import { useLinkedIssuesAvailable } from 'scenes/session-recordings/player/sidebar/useLinkedIssuesAvailable'
import { isFeedReplayLayout } from 'scenes/session-recordings/playlist/replayLayout'

import { SessionRecordingSidebarTab } from '~/types'

import { debugTabKeys } from './DebugTabBar'
import { QuillPlayerActions } from './QuillPlayerActions'
import { QuillWindowSelect } from './QuillWindowSelect'

type PlayerMode = 'watch' | 'debug'

export function PlayerModeBar(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { currentURL, loading } = useValues(playerMetaLogic(logicProps))
    const { debugMode, replayLayout } = useValues(playerSettingsLogic)
    const { setDebugMode } = useActions(playerSettingsLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const debugTabs = debugTabKeys(useLinkedIssuesAvailable())
    const { ref, size } = useResizeBreakpoints({ 0: 'small', 600: 'normal' })

    const controlsBelow = isFeedReplayLayout(replayLayout)
    const setMode = (next: PlayerMode): void => {
        posthog.capture('session recording mode changed', { mode: next })
        setDebugMode(next === 'debug')
        if (next === 'debug' && !debugTabs.includes(activeTab)) {
            setTab(SessionRecordingSidebarTab.INSPECTOR)
        }
    }

    const { urlToUse, isWebUrl } = parseUrl(currentURL)
    const devModeToggle = (
        <Toggle
            variant="outline"
            size="sm"
            pressed={debugMode}
            onPressedChange={(pressed) => setMode(pressed ? 'debug' : 'watch')}
            className="shrink-0 text-xs aria-pressed:translate-none aria-pressed:border-(--primary) aria-pressed:bg-(--primary) aria-pressed:text-(--primary-foreground)"
            data-attr="player-mode-debug"
        >
            <IconBug />
            Dev mode
        </Toggle>
    )

    return (
        <div ref={ref} data-quill className="PlayerMeta relative text-foreground">
            <div className="flex flex-row items-center gap-x-1 whitespace-nowrap overflow-hidden px-1 py-1 text-xs">
                {!controlsBelow && devModeToggle}
                {!controlsBelow && <QuillWindowSelect />}
                {loading ? (
                    <Skeleton className="w-1/3 h-4 my-1" />
                ) : (
                    <>
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
                {controlsBelow ? devModeToggle : <QuillPlayerActions size={size} />}
            </div>
        </div>
    )
}
