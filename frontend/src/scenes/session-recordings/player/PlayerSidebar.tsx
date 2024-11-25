import { IconBottomPanel, IconSidePanel, IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useRef } from 'react'

import { SessionRecordingSidebarStacking, SessionRecordingSidebarTab } from '~/types'

import { TabToIcon } from './inspector/PlayerInspectorControls'
import { PlayerPersonMeta } from './PlayerPersonMeta'
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

    const sidebarTabs = [SessionRecordingSidebarTab.OVERVIEW, SessionRecordingSidebarTab.INSPECTOR]

    if (window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
        sidebarTabs.push(SessionRecordingSidebarTab.DEBUGGER)
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
            {sidebarOpen ? (
                <>
                    <div className="flex bg-bg-light">
                        <div className="w-2.5 border-b shrink-0" />
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={(tabId) => setTab(tabId)}
                            tabs={sidebarTabs.map((tabId) => ({
                                key: tabId,
                                label: capitalizeFirstLetter(tabId),
                            }))}
                            barClassName="mb-0"
                            size="small"
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
            ) : (
                <div className="flex flex-col items-center gap-1 px-1 pt-2">
                    <PlayerPersonMeta />
                    {Object.values(TabToIcon).map((Icon, idx) => {
                        return Icon ? (
                            <LemonButton
                                key={idx}
                                size="small"
                                icon={<Icon />}
                                onClick={() => {
                                    setSidebarOpen(true)
                                    setTab(SessionRecordingSidebarTab.INSPECTOR)
                                }}
                            />
                        ) : null
                    })}
                </div>
            )}
        </div>
    )
}
