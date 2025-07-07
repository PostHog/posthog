import { IconBottomPanel, IconSidePanel, IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, splitKebabCase } from 'lib/utils'
import { useRef } from 'react'

import { SessionRecordingSidebarStacking, SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from './playerSettingsLogic'
import { playerSidebarLogic } from './sidebar/playerSidebarLogic'
import { PlayerSidebarTab } from './sidebar/PlayerSidebarTab'

export function PlayerSidebar(): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const { sidebarOpen, preferredSidebarStacking, isVerticallyStacked } = useValues(playerSettingsLogic)
    const { setSidebarOpen, setPreferredSidebarStacking } = useActions(playerSettingsLogic)

    const logicKey = `player-sidebar-${isVerticallyStacked ? 'vertical' : 'horizontal'}`

    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: ref,
        persistent: true,
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

    // Show AI summary tab in the second position if the flag is enabled
    if (featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY]) {
        sidebarTabs.splice(1, 0, SessionRecordingSidebarTab.SESSION_SUMMARY)
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
            />
            {sidebarOpen && (
                <>
                    <div className="flex bg-surface-primary pt-[1px]">
                        <div className="w-2.5 border-b shrink-0" />
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={(tabId) => setTab(tabId)}
                            tabs={sidebarTabs.map((tabId) => {
                                if (tabId === SessionRecordingSidebarTab.SESSION_SUMMARY) {
                                    return {
                                        key: tabId,
                                        label: 'AI summary',
                                    }
                                }

                                return {
                                    key: tabId,
                                    label: capitalizeFirstLetter(splitKebabCase(tabId)),
                                }
                            })}
                            barClassName="!mb-0"
                            size="small"
                            className="overflow-x-auto"
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
                </>
            )}
        </div>
    )
}
