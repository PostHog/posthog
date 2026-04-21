import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconBottomPanel, IconSidePanel, IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { capitalizeFirstLetter, splitKebabCase } from 'lib/utils'

import { SessionRecordingSidebarStacking, SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from './playerSettingsLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { playerSidebarLogic } from './sidebar/playerSidebarLogic'
import { PlayerSidebarTab } from './sidebar/PlayerSidebarTab'

export function PlayerSidebar(): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const { sidebarOpen, preferredSidebarStacking, isVerticallyStacked } = useValues(playerSettingsLogic)
    const { setSidebarOpen, setPreferredSidebarStacking } = useActions(playerSettingsLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)

    const logicKey = `player-sidebar-${isVerticallyStacked ? 'vertical' : 'horizontal'}`

    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: ref,
        persistent: true,
        persistPrefix: '2025-12-29',
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'top' : 'left',
        onToggleClosed: (shouldBeClosed) => setSidebarOpen(!shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    const sidebarTabs = [
        SessionRecordingSidebarTab.OVERVIEW,
        SessionRecordingSidebarTab.INSPECTOR,
        SessionRecordingSidebarTab.NETWORK_WATERFALL,
    ]

    // Show linked issues tab if there are integrations or existing references
    const sessionReplayIntegrations = getIntegrationsByKind(['linear', 'github', 'gitlab', 'jira'])
    const externalReferences = sessionPlayerMetaData?.external_references ?? []

    if (sessionReplayIntegrations.length > 0 || externalReferences.length > 0) {
        sidebarTabs.push(SessionRecordingSidebarTab.LINKED_ISSUES)
    }

    return (
        <div
            className={clsx(
                'SessionRecordingPlayer__sidebar',
                !sidebarOpen && 'SessionRecordingPlayer__sidebar--collapsed'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                !sidebarOpen
                    ? {}
                    : isVerticallyStacked
                      ? { height: desiredSize ?? undefined, minHeight: 210 }
                      : { width: desiredSize ?? undefined }
            }
        >
            <Resizer
                logicKey={logicKey}
                placement={sidebarOpen && isVerticallyStacked ? 'top' : 'left'}
                containerRef={ref}
                closeThreshold={100}
                offset="0.25rem"
            />
            {sidebarOpen && (
                <div className="SessionRecordingPlayer__sidebar__content">
                    <div className="flex bg-surface-primary pt-[1px]">
                        <div className="w-2.5 border-b shrink-0" />
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={(tabId) => setTab(tabId)}
                            tabs={sidebarTabs.map((tabId) => ({
                                key: tabId,
                                label: capitalizeFirstLetter(splitKebabCase(tabId)),
                            }))}
                            barClassName="!mb-0"
                            size="small"
                            className="overflow-x-auto hide-scrollbar"
                        />
                        <div className="flex flex-1 border-b shrink-0" />
                        <div className="flex gap-1 border-b end">
                            <LemonButton
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
