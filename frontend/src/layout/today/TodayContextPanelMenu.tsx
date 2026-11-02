import { useActions, useValues } from 'kea'

import { IconEllipsis, IconSidePanel } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { IconOpenFullScreen, IconUndockPanel } from 'lib/lemon-ui/icons'
import { PhaiViewSwitchMenuItem } from 'scenes/max/components/PhaiViewSwitchMenuItem'

import { SidePanelTab } from '~/types'

import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'
import { DebugLogsMenuItem } from 'products/posthog_ai/frontend/api/menus'

import { todayAiChatLogic } from './todayAiChatLogic'
import { todayContextPanelLogic } from './todayContextPanelLogic'
import { DROPDOWN_PARTS } from './todayMenuParts'
import { TodayPanelTaskMenuItems } from './TodayPanelTaskMenuItems'

export function TodayContextPanelMenu({ docked }: { docked: boolean }): JSX.Element | null {
    const { activeTab, fullScreenUrl } = useValues(todayContextPanelLogic)
    // Reading sidepanelTicketsLogic mounts it, and mounting it fetches tickets. Only the Support tab reads it,
    // because the support panel next to this menu already has it mounted.
    return activeTab === SidePanelTab.Support ? (
        <SupportPanelMenu docked={docked} />
    ) : (
        <PanelMenu docked={docked} tabFullScreenUrl={fullScreenUrl} />
    )
}

function SupportPanelMenu({ docked }: { docked: boolean }): JSX.Element | null {
    const { myTicketsUrl } = useValues(sidepanelTicketsLogic)
    return <PanelMenu docked={docked} tabFullScreenUrl={myTicketsUrl} />
}

function PanelMenu({
    docked,
    tabFullScreenUrl,
}: {
    docked: boolean
    tabFullScreenUrl: string | null
}): JSX.Element | null {
    const { activeTab, canUndock } = useValues(todayContextPanelLogic)
    const { dock, undock, openFullScreen } = useActions(todayContextPanelLogic)
    const { fullScreenUrl: aiFullScreenUrl, onTaskRunner, activeCreation } = useValues(todayAiChatLogic)
    const { carryContextToFullScreen } = useActions(todayAiChatLogic)
    const onAi = activeTab === SidePanelTab.Max
    const fullScreenUrl = onAi ? aiFullScreenUrl : tabFullScreenUrl
    const chatTask = onAi && onTaskRunner ? activeCreation : null
    const canMove = !!fullScreenUrl || !docked || canUndock

    // A docked canvas tab has nowhere to go and no settings, so it gets no menu.
    if (!canMove && !onAi) {
        return null
    }

    const placement = (
        <>
            {fullScreenUrl && (
                <DROPDOWN_PARTS.Item
                    to={fullScreenUrl}
                    onClick={() => {
                        if (onAi) {
                            carryContextToFullScreen()
                        }
                        openFullScreen()
                    }}
                    dataAttr="today-context-panel-full-screen"
                >
                    <IconOpenFullScreen />
                    Open full screen
                </DROPDOWN_PARTS.Item>
            )}
            {docked ? (
                canUndock && (
                    <DROPDOWN_PARTS.Item onClick={undock} dataAttr="today-context-panel-undock">
                        <IconUndockPanel />
                        Undock
                    </DROPDOWN_PARTS.Item>
                )
            ) : (
                <DROPDOWN_PARTS.Item onClick={dock} dataAttr="today-context-panel-dock">
                    <IconSidePanel />
                    Dock to the right
                </DROPDOWN_PARTS.Item>
            )}
        </>
    )

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon"
                                    aria-label="More options"
                                    className="text-muted-foreground hover:text-foreground"
                                    data-attr="today-context-panel-more"
                                />
                            }
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent side="bottom">More options</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="min-w-56 max-w-80">
                {chatTask?.taskId && chatTask.runId ? (
                    <TodayPanelTaskMenuItems taskId={chatTask.taskId} runId={chatTask.runId} placement={placement} />
                ) : (
                    <>
                        {placement}
                        {onAi && (
                            <>
                                {canMove && <DropdownMenuSeparator />}
                                {onTaskRunner && <DebugLogsMenuItem parts={DROPDOWN_PARTS} />}
                                <PhaiViewSwitchMenuItem />
                            </>
                        )}
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
