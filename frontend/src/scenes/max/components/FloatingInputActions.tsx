import {
    IconChevronDown,
    IconClockRewind,
    IconEllipsis,
    IconGear,
    IconLightBulb,
    IconPlus,
    IconSidePanel,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, Tooltip } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { maxLogic } from '../maxLogic'

interface FloatingInputActionsProps {
    showSuggestions: boolean
    onCollapse: () => void
    isThreadVisible: boolean
}

export function FloatingInputActions({
    showSuggestions,
    onCollapse,
    isThreadVisible,
}: FloatingInputActionsProps): JSX.Element {
    const { setShowSuggestions, toggleConversationHistory, setActiveGroup } = useActions(maxLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
    const { startNewConversation } = useActions(maxLogic)

    const menuItems: LemonMenuItems = [
        {
            label: 'Open in sidebar',
            icon: <IconSidePanel />,
            onClick: () => openSidePanel(SidePanelTab.Max),
            size: 'xsmall',
        },
        {
            label: 'Open conversation history',
            icon: <IconClockRewind />,
            onClick: () => {
                toggleConversationHistory()
                openSidePanel(SidePanelTab.Max)
            },
            size: 'xsmall',
        },
        {
            label: "Edit Max's memory",
            icon: <IconGear />,
            onClick: () => openSettingsPanel({ sectionId: 'environment-max', settingId: 'core-memory' }),
            size: 'xsmall',
        },
    ]

    return (
        <>
            {!isThreadVisible && (
                <Tooltip title={showSuggestions ? 'Hide suggestions' : 'Show suggestions'} placement="top" delayMs={0}>
                    <LemonButton
                        size="xxsmall"
                        icon={
                            showSuggestions ? (
                                <IconChevronDown className="size-3" />
                            ) : (
                                <IconLightBulb className="size-3" />
                            )
                        }
                        type="tertiary"
                        onClick={() => {
                            setShowSuggestions(!showSuggestions)
                            setActiveGroup(null)
                        }}
                    />
                </Tooltip>
            )}
            {isThreadVisible && (
                <Tooltip title="Start a new chat" placement="top" delayMs={0}>
                    <LemonButton
                        size="xxsmall"
                        icon={<IconPlus className="size-3" />}
                        type="tertiary"
                        onClick={() => startNewConversation()}
                    />
                </Tooltip>
            )}
            <LemonMenu items={menuItems} placement="bottom-end">
                <LemonButton size="xxsmall" icon={<IconEllipsis className="size-3" />} type="tertiary" />
            </LemonMenu>
            <Tooltip title="Minimize" placement="top" delayMs={0}>
                <LemonButton size="xxsmall" icon={<IconX className="size-3" />} type="tertiary" onClick={onCollapse} />
            </Tooltip>
        </>
    )
}
