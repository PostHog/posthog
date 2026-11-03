import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronDown, IconSidePanel, IconSparkles } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { PaneTab, PaneTabBar } from 'scenes/session-recordings/components/PaneTabBar'
import {
    WatchPanelTab,
    isDebugWatchPanelTab,
    playerSettingsLogic,
} from 'scenes/session-recordings/player/playerSettingsLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'
import { PlayerSidebarTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarTab'
import { useLinkedIssuesAvailable } from 'scenes/session-recordings/player/sidebar/useLinkedIssuesAvailable'

import { debugPaneTabs, debugTabKeys } from './DebugTabBar'
import { RecordingOverviewPanels } from './RecordingOverviewPanels'

export interface ObservationsTab {
    count: number
    hasObservations: boolean
    content: ReactNode
}

export function WatchPanelTabs({
    observations,
    debug,
}: {
    observations?: ObservationsTab
    debug: boolean
}): JSX.Element {
    const { watchPanelTab, watchPanelCollapsed } = useValues(playerSettingsLogic)
    const { setWatchPanelTab, setWatchPanelCollapsed, setWatchDebugDock } = useActions(playerSettingsLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const linkedIssuesAvailable = useLinkedIssuesAvailable()

    const tabs: PaneTab<WatchPanelTab>[] = [
        { key: 'overview', label: 'Overview', dataAttr: 'watch-panel-section-overview' },
        ...(observations
            ? [
                  {
                      key: 'observations' as const,
                      label: (
                          <>
                              Observations
                              {observations.count > 0 && <Badge>{observations.count}</Badge>}
                          </>
                      ),
                      icon: <IconSparkles />,
                      dataAttr: 'watch-panel-section-observations',
                  },
              ]
            : []),
        ...(debug
            ? debugPaneTabs(debugTabKeys(linkedIssuesAvailable).filter(isDebugWatchPanelTab)).map((tab, index) => ({
                  ...tab,
                  dividerBefore: index === 0,
              }))
            : []),
    ]
    if (tabs.length === 1) {
        return <RecordingOverviewPanels />
    }
    const tab =
        tabs.find((candidate) => candidate.key === watchPanelTab)?.key ??
        (observations?.hasObservations ? 'observations' : 'overview')

    const select = (key: WatchPanelTab): void => {
        setWatchPanelTab(key)
        if (key !== 'overview' && key !== 'observations') {
            setTab(key)
        }
    }

    return (
        <div
            data-quill
            className="flex flex-col border border-border rounded overflow-hidden"
            data-attr="watch-panel-tabs"
        >
            <PaneTabBar tabs={tabs} activeKey={tab} onChange={select}>
                <Button
                    size="icon"
                    onClick={() => setWatchPanelCollapsed(!watchPanelCollapsed)}
                    tooltip={watchPanelCollapsed ? 'Expand' : 'Collapse'}
                    aria-label={watchPanelCollapsed ? 'Expand' : 'Collapse'}
                    className="rounded-none"
                    data-attr="watch-panel-collapse"
                >
                    <IconChevronDown className={watchPanelCollapsed ? undefined : 'rotate-180'} />
                </Button>
                {debug && (
                    <Button
                        size="icon"
                        onClick={() => setWatchDebugDock('right')}
                        tooltip="Dock to right"
                        aria-label="Dock to right"
                        className="rounded-none"
                        data-attr="player-sidebar-dock-toggle"
                    >
                        <IconSidePanel />
                    </Button>
                )}
            </PaneTabBar>
            <div
                className={clsx(
                    'grid motion-safe:transition-[grid-template-rows] motion-safe:duration-200',
                    watchPanelCollapsed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
                )}
            >
                <div className="min-h-0 overflow-hidden">
                    {tab === 'overview' ? (
                        <RecordingOverviewPanels />
                    ) : tab === 'observations' ? (
                        observations?.content
                    ) : (
                        <div
                            data-not-quill
                            className="SessionRecordingPlayerWrapper__dock-in flex flex-col min-w-0 overflow-hidden h-[calc(45cqh-1.5rem)] min-h-48"
                            data-attr="watch-panel-debug"
                        >
                            <PlayerSidebarTab tab={tab} />
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
