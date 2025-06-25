import { IconChevronDown, IconLightBulb, IconOpenSidebar, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'

interface FloatingInputActionsProps {
    onCollapse: () => void
    isThreadVisible: boolean
}

export function FloatingInputActions({ onCollapse, isThreadVisible }: FloatingInputActionsProps): JSX.Element {
    const { setActiveGroup, startNewConversation } = useActions(maxLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { setIsFloatingMaxExpanded, setShowFloatingMaxSuggestions } = useActions(maxGlobalLogic)
    const { showFloatingMaxSuggestions } = useValues(maxGlobalLogic)

    return (
        <>
            {!isThreadVisible && (
                <Tooltip
                    title={showFloatingMaxSuggestions ? 'Hide suggestions' : 'Show suggestions'}
                    placement="top"
                    delayMs={0}
                >
                    <LemonButton
                        size="xxsmall"
                        icon={
                            showFloatingMaxSuggestions ? (
                                <IconChevronDown className="size-3" />
                            ) : (
                                <IconLightBulb className="size-3" />
                            )
                        }
                        type="tertiary"
                        onClick={() => {
                            setShowFloatingMaxSuggestions(!showFloatingMaxSuggestions)
                            setActiveGroup(null)
                        }}
                    />
                </Tooltip>
            )}
            {isThreadVisible && (
                <LemonButton
                    size="xxsmall"
                    icon={<IconPlus className="size-3" />}
                    type="tertiary"
                    onClick={() => startNewConversation()}
                    tooltip="Start a new chat"
                />
            )}
            <Tooltip title="Expand to side panel" placement="top" delayMs={0}>
                <LemonButton
                    size="xxsmall"
                    icon={<IconOpenSidebar className="size-3" />}
                    type="tertiary"
                    onClick={() => {
                        openSidePanel(SidePanelTab.Max)
                        setIsFloatingMaxExpanded(false)
                    }}
                />
            </Tooltip>
            <Tooltip title="Close" placement="top" delayMs={0}>
                <LemonButton size="xxsmall" icon={<IconX className="size-3" />} type="tertiary" onClick={onCollapse} />
            </Tooltip>
        </>
    )
}
