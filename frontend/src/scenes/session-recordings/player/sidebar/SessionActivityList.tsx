import { useActions, useValues } from 'kea'

import { IconBottomPanel, IconSidePanel, IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, splitKebabCase } from 'lib/utils'

import { SessionRecordingSidebarStacking, SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { PlayerSidebarTab } from './PlayerSidebarTab'
import { playerSidebarLogic } from './playerSidebarLogic'

export interface PlayerSidebarContentProps {
    onClose?: () => void
    showControls?: boolean
}

export function PlayerSidebarContent({ onClose, showControls = true }: PlayerSidebarContentProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    const { preferredSidebarStacking, isVerticallyStacked } = useValues(playerSettingsLogic)
    const { setSidebarOpen, setPreferredSidebarStacking } = useActions(playerSettingsLogic)

    const sidebarTabs = [
        SessionRecordingSidebarTab.OVERVIEW,
        SessionRecordingSidebarTab.INSPECTOR,
        SessionRecordingSidebarTab.NETWORK_WATERFALL,
    ]

    if (featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY]) {
        sidebarTabs.splice(1, 0, SessionRecordingSidebarTab.SESSION_SUMMARY)
    }

    const handleClose = onClose ?? (() => setSidebarOpen(false))

    return (
        <>
            <div className="flex bg-surface-primary pt-[1px] shrink-0">
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
                {showControls && (
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
                        <LemonButton size="small" icon={<IconX />} onClick={handleClose} tooltip="Close sidebar" />
                    </div>
                )}
            </div>
            <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                <PlayerSidebarTab />
            </div>
        </>
    )
}
