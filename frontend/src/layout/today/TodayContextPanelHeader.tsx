import { useActions, useValues } from 'kea'

import { IconExpand45, IconX } from '@posthog/icons'
import { Button, CardHeader, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/sidePanelTabs'

import { todayContextPanelLogic } from './todayContextPanelLogic'

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

export function TodayContextPanelHeader(): JSX.Element {
    const { activeTab, fullScreenUrl } = useValues(todayContextPanelLogic)
    const { close, openFullScreen } = useActions(todayContextPanelLogic)

    return (
        <CardHeader className="flex items-center gap-1 border-b border-border py-1.5 ps-1.5 pe-1.5">
            <span className="flex h-7 min-w-0 items-center px-1.5 font-semibold">
                <span className="truncate">{SIDE_PANEL_TABS[activeTab].label}</span>
            </span>
            <div className="ms-auto flex shrink-0 items-center gap-0.5">
                {fullScreenUrl && (
                    <HeaderIconButton
                        label="Open full screen"
                        dataAttr="today-context-panel-full-screen"
                        onClick={openFullScreen}
                        render={<LinkPrimitive to={fullScreenUrl} />}
                    >
                        <IconExpand45 />
                    </HeaderIconButton>
                )}
                <HeaderIconButton label="Close" onClick={close} dataAttr="today-context-panel-close">
                    <IconX />
                </HeaderIconButton>
            </div>
        </CardHeader>
    )
}
