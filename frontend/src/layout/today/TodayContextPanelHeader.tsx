import { useActions, useValues } from 'kea'

import { IconExpand45, IconExternal, IconPlus, IconSidePanel, IconX } from '@posthog/icons'
import { Button, CardHeader, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/sidePanelTabs'
import { SidePanelTab } from '~/types'

import { todayAiChatLogic } from './todayAiChatLogic'
import { TodayAiChatTitleMenu } from './TodayAiChatTitleMenu'
import { todayContextPanelLogic } from './todayContextPanelLogic'

interface TodayContextPanelHeaderProps {
    docked: boolean
    /** Starts moving the floating panel. Left out when docked, since a docked panel doesn't move. */
    onDragStart?: (event: React.PointerEvent<HTMLDivElement>) => void
}

function HeaderIconButton({
    label,
    dataAttr,
    onClick,
    render,
    children,
}: {
    label: string
    dataAttr: string
    onClick?: () => void
    render?: React.ReactElement
    children: React.ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        aria-label={label}
                        className="text-muted-foreground hover:text-foreground"
                        onClick={onClick}
                        render={render}
                        data-attr={dataAttr}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent side="bottom">{label}</TooltipContent>
        </Tooltip>
    )
}

export function TodayContextPanelHeader({ docked, onDragStart }: TodayContextPanelHeaderProps): JSX.Element {
    const { activeTab, fullScreenUrl: tabFullScreenUrl, canUndock } = useValues(todayContextPanelLogic)
    const { dock, undock, close, openFullScreen } = useActions(todayContextPanelLogic)
    const { fullScreenUrl: aiFullScreenUrl } = useValues(todayAiChatLogic)
    const { startNewChat, carryContextToFullScreen } = useActions(todayAiChatLogic)
    const fullScreenUrl = activeTab === SidePanelTab.Max ? aiFullScreenUrl : tabFullScreenUrl

    return (
        <CardHeader
            className={cn(
                'flex items-center gap-1 border-b border-border py-1.5 ps-1.5 pe-1.5',
                onDragStart && 'cursor-grab touch-none select-none active:cursor-grabbing'
            )}
            onPointerDown={onDragStart}
        >
            {activeTab === SidePanelTab.Max ? (
                <TodayAiChatTitleMenu />
            ) : (
                // As tall as the chat's title button, so the header keeps its height across tabs.
                <span className="flex h-7 min-w-0 items-center px-1.5 font-semibold">
                    <span className="truncate">{SIDE_PANEL_TABS[activeTab].label}</span>
                </span>
            )}
            <div className="ms-auto flex shrink-0 items-center gap-0.5">
                {activeTab === SidePanelTab.Max && (
                    <HeaderIconButton label="New chat" onClick={startNewChat} dataAttr="today-ai-chat-new">
                        <IconPlus />
                    </HeaderIconButton>
                )}
                {fullScreenUrl && (
                    <HeaderIconButton
                        label="Open full screen"
                        dataAttr="today-context-panel-full-screen"
                        onClick={() => {
                            if (activeTab === SidePanelTab.Max) {
                                carryContextToFullScreen()
                            }
                            openFullScreen()
                        }}
                        render={<LinkPrimitive to={fullScreenUrl} />}
                    >
                        <IconExpand45 />
                    </HeaderIconButton>
                )}
                {docked ? (
                    canUndock && (
                        <HeaderIconButton label="Undock" onClick={undock} dataAttr="today-context-panel-undock">
                            <IconExternal />
                        </HeaderIconButton>
                    )
                ) : (
                    <HeaderIconButton label="Dock to the right" onClick={dock} dataAttr="today-context-panel-dock">
                        <IconSidePanel />
                    </HeaderIconButton>
                )}
                <HeaderIconButton label="Close" onClick={close} dataAttr="today-context-panel-close">
                    <IconX />
                </HeaderIconButton>
            </div>
        </CardHeader>
    )
}
