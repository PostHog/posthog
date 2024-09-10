import { IconBottomPanel, IconPerson, IconSidePanel, IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useRef } from 'react'

import { SessionRecordingSidebarTab } from '~/types'

import { NetworkView } from '../apm/NetworkView'
import { PlayerInspectorControls, TabToIcon } from './inspector/PlayerInspectorControls'
import { PlayerInspectorList } from './inspector/PlayerInspectorList'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { playerSidebarLogic } from './sidebar/playerSidebarLogic'

export function PlayerSidebar({
    isVerticallyStacked,
    toggleLayoutStacking,
}: {
    isVerticallyStacked: boolean
    toggleLayoutStacking?: () => void
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const sidebarLogic = playerSidebarLogic(logicProps)
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(sidebarLogic)
    const { setTab } = useActions(sidebarLogic)

    const logicKey = `player-sidebar-${isVerticallyStacked ? 'vertical' : 'horizontal'}`

    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: ref,
        persistent: true,
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'top' : 'left',
        onToggleClosed: (shouldBeClosed) => setTab(shouldBeClosed ? null : SessionRecordingSidebarTab.SESSION),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    const sidebarTabs = [
        SessionRecordingSidebarTab.SESSION,
        SessionRecordingSidebarTab.INSPECTOR,
        SessionRecordingSidebarTab.WATERFALL,
    ]

    if (window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
        sidebarTabs.push(SessionRecordingSidebarTab.DEBUGGER)
    }

    const collapsed = activeTab === null

    return (
        <div
            className={clsx(
                'SessionRecordingPlayer__sidebar',
                collapsed && 'SessionRecordingPlayer__sidebar--collapsed'
            )}
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                collapsed
                    ? {}
                    : isVerticallyStacked
                    ? { height: desiredSize ?? undefined, minHeight: 110 }
                    : { width: desiredSize ?? undefined }
            }
        >
            <Resizer
                logicKey={logicKey}
                placement={isVerticallyStacked ? 'top' : 'left'}
                containerRef={ref}
                closeThreshold={100}
            />
            {activeTab ? (
                <>
                    <div className="flex bg-bg-light">
                        <div className="w-2.5 border-b shrink-0" />
                        <LemonTabs
                            // size="small"
                            activeKey={activeTab}
                            onChange={(tabId) => setTab(tabId)}
                            tabs={sidebarTabs.map((tabId) => ({
                                key: tabId,
                                label: capitalizeFirstLetter(tabId),
                            }))}
                            barClassName="mb-0 SessionRecordingPlayer__sidebar__tabs"
                        />
                        <div className="flex flex-1 border-b shrink-0" />
                        <div className="flex gap-1 border-b px-1 items-center">
                            {toggleLayoutStacking && (
                                <LemonButton
                                    size="xsmall"
                                    icon={isVerticallyStacked ? <IconSidePanel /> : <IconBottomPanel />}
                                    onClick={toggleLayoutStacking}
                                />
                            )}
                            <LemonButton size="xsmall" icon={<IconX />} onClick={() => setTab(null)} />
                        </div>
                    </div>
                    {activeTab === SessionRecordingSidebarTab.INSPECTOR ? (
                        <>
                            <PlayerInspectorControls />
                            <PlayerInspectorList />
                        </>
                    ) : activeTab === SessionRecordingSidebarTab.WATERFALL ? (
                        <NetworkView sessionRecordingId={logicProps.sessionRecordingId} />
                    ) : activeTab === SessionRecordingSidebarTab.SESSION ? (
                        <div>New session tab</div>
                    ) : (
                        <div>Debugger tab</div>
                    )}
                </>
            ) : (
                <div className="flex flex-col items-center gap-1 p-1">
                    <LemonButton
                        size="small"
                        icon={<IconPerson />}
                        onClick={() => {
                            setTab(SessionRecordingSidebarTab.SESSION)
                        }}
                    />
                    {Object.values(TabToIcon).map((Icon, idx) => {
                        return Icon ? (
                            <LemonButton
                                key={idx}
                                size="small"
                                icon={<Icon />}
                                onClick={() => {
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
