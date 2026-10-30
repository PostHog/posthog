import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconBottomPanel, IconSidePanel, IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, splitKebabCase } from 'lib/utils/strings'

import { SessionRecordingSidebarStacking, SessionRecordingSidebarTab } from '~/types'

import { visionSurfaceShown } from 'products/replay_vision/frontend/utils/visionSurface'

import { playerSettingsLogic } from './playerSettingsLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { playerSidebarLogic } from './sidebar/playerSidebarLogic'
import { PlayerSidebarTab } from './sidebar/PlayerSidebarTab'
import { useLinkedIssuesAvailable } from './sidebar/useLinkedIssuesAvailable'
import { DebugTabBar } from './watch/DebugTabBar'

export function PlayerSidebar({
    tabs,
    stacking,
    onToggleStacking,
}: {
    tabs?: SessionRecordingSidebarTab[]
    stacking?: SessionRecordingSidebarStacking
    onToggleStacking?: () => void
} = {}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const {
        sidebarOpen,
        debugMode,
        preferredSidebarStacking,
        isVerticallyStacked: preferredVertical,
    } = useValues(playerSettingsLogic)
    const isVerticallyStacked = stacking ? stacking === SessionRecordingSidebarStacking.Vertical : preferredVertical
    const { setSidebarOpen, setDebugMode, setPreferredSidebarStacking } = useActions(playerSettingsLogic)
    const open = tabs ? debugMode : sidebarOpen
    const setOpen = tabs ? setDebugMode : setSidebarOpen
    const { sessionPlayerMetaData, logicProps } = useValues(sessionRecordingPlayerLogic)
    const linkedIssuesAvailable = useLinkedIssuesAvailable()
    const { featureFlags } = useValues(featureFlagLogic)

    const logicKey = `player-sidebar-${isVerticallyStacked ? 'vertical' : 'horizontal'}`

    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: ref,
        persistent: true,
        persistPrefix: '2025-12-29',
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'top' : 'left',
        onToggleClosed: (shouldBeClosed) => setOpen(!shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    const debugTab = tabs?.includes(activeTab) ? activeTab : SessionRecordingSidebarTab.INSPECTOR
    const sidebarTabs = tabs
        ? [...tabs]
        : [
              SessionRecordingSidebarTab.OVERVIEW,
              SessionRecordingSidebarTab.INSPECTOR,
              SessionRecordingSidebarTab.NETWORK_WATERFALL,
          ]

    if (!tabs && visionSurfaceShown(logicProps)) {
        sidebarTabs.push(SessionRecordingSidebarTab.OBSERVATIONS)
    }

    // Show the person's other recordings once we know who they are
    if (!tabs && featureFlags[FEATURE_FLAGS.REPLAY_PLAYER_PERSON_SESSIONS_TAB] && sessionPlayerMetaData?.person) {
        sidebarTabs.push(SessionRecordingSidebarTab.SESSIONS)
    }

    if (!tabs && linkedIssuesAvailable) {
        sidebarTabs.push(SessionRecordingSidebarTab.LINKED_ISSUES)
    }

    return (
        <div
            className={clsx('SessionRecordingPlayer__sidebar', !open && 'SessionRecordingPlayer__sidebar--collapsed')}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                !open
                    ? {}
                    : isVerticallyStacked
                      ? { height: desiredSize ?? undefined, minHeight: 210 }
                      : { width: desiredSize ?? undefined }
            }
        >
            <Resizer
                logicKey={logicKey}
                placement={open && isVerticallyStacked ? 'top' : 'left'}
                containerRef={ref}
                closeThreshold={100}
                offset="0.25rem"
            />
            {open && tabs && (
                <div className="SessionRecordingPlayer__sidebar__content">
                    <div className="flex flex-col flex-1 min-h-0 h-full">
                        <DebugTabBar tabs={sidebarTabs} activeTab={debugTab} onChange={setTab}>
                            <LemonButton
                                data-attr="player-sidebar-dock-toggle"
                                size="small"
                                icon={<IconBottomPanel />}
                                onClick={() => onToggleStacking?.()}
                                tooltip="Dock to bottom"
                                aria-label="Dock to bottom"
                                className="rounded-none"
                            />
                            <LemonButton
                                data-attr="player-sidebar-close"
                                size="small"
                                icon={<IconX />}
                                onClick={() => setDebugMode(false)}
                                tooltip="Close sidebar"
                                aria-label="Close sidebar"
                                className="rounded-none"
                            />
                        </DebugTabBar>
                        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
                            <PlayerSidebarTab tab={debugTab} />
                        </div>
                    </div>
                </div>
            )}
            {open && !tabs && (
                <div className="SessionRecordingPlayer__sidebar__content">
                    <div className="flex bg-surface-primary pt-[1px]">
                        <div className="w-2.5 border-b shrink-0" />
                        <LemonTabs
                            data-attr="player-sidebar-tabs"
                            activeKey={activeTab}
                            onChange={(tabId) => setTab(tabId)}
                            tabs={sidebarTabs.map((tabId) => ({
                                key: tabId,
                                label: capitalizeFirstLetter(splitKebabCase(tabId)),
                                'data-attr': `player-sidebar-tab-${tabId}`,
                            }))}
                            // The root scrolls, not the bar, so the scrollbar cannot collide with the bar's bottom-anchored underline
                            barClassName="!mb-0 w-max min-w-full !overflow-x-visible"
                            size="small"
                            // Fills the row rather than hugging the tabs, so subpixel tab widths cannot leave a scrollbar with nothing to scroll
                            className="flex-1 min-w-0 overflow-x-auto overflow-y-clip !self-start"
                        />
                        <div className="flex gap-1 border-b end">
                            <LemonButton
                                data-attr="player-sidebar-dock-toggle"
                                size="small"
                                icon={isVerticallyStacked ? <IconSidePanel /> : <IconBottomPanel />}
                                onClick={() =>
                                    setPreferredSidebarStacking(
                                        preferredSidebarStacking === SessionRecordingSidebarStacking.Vertical
                                            ? SessionRecordingSidebarStacking.Horizontal
                                            : SessionRecordingSidebarStacking.Vertical
                                    )
                                }
                                tooltip={`Dock to ${isVerticallyStacked ? 'right' : 'bottom'}`}
                            />
                            <LemonButton
                                data-attr="player-sidebar-close"
                                size="small"
                                icon={<IconX />}
                                onClick={() => setSidebarOpen(false)}
                                tooltip="Close sidebar"
                            />
                        </div>
                    </div>
                    <PlayerSidebarTab />
                </div>
            )}
        </div>
    )
}
