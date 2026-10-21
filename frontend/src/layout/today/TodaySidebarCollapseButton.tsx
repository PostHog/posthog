import { useActions, useValues } from 'kea'

import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { IconHideSidebar, TODAY_PANES, todaySidebarShortcutLabel } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

// Both icons share one grid cell and cross-fade. Touch screens have no hover, so they show the hide icon.
const ICON =
    'col-start-1 row-start-1 flex transition-[opacity,scale] duration-150 ease-[ease] motion-reduce:transition-none'
const SHOWN_ON_HOVER = cn(
    'pointer-fine:scale-90 pointer-fine:opacity-0',
    'pointer-fine:group-hover/sidebar:scale-100 pointer-fine:group-hover/sidebar:opacity-100',
    'pointer-fine:group-has-[:focus-visible]/sidebar:scale-100 pointer-fine:group-has-[:focus-visible]/sidebar:opacity-100'
)
const HIDDEN_ON_HOVER = cn(
    'scale-90 opacity-0 pointer-fine:scale-100 pointer-fine:opacity-100',
    'pointer-fine:group-hover/sidebar:scale-90 pointer-fine:group-hover/sidebar:opacity-0',
    'pointer-fine:group-has-[:focus-visible]/sidebar:scale-90 pointer-fine:group-has-[:focus-visible]/sidebar:opacity-0'
)

/** Hides the sidebar from its own title row. The scene header then shows the pane title to open it again. */
export function TodaySidebarCollapseButton(): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { toggleSidebar } = useActions(todayShellLogic)

    return (
        <Tooltip disableHoverablePopup>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        className="-ms-2 shrink-0 text-muted-foreground"
                        aria-label="Hide sidebar"
                        data-attr="today-pane-hide-sidebar"
                        onClick={() => toggleSidebar('pane_header')}
                    />
                }
            >
                <span className="grid">
                    <span className={cn(ICON, HIDDEN_ON_HOVER)}>{TODAY_PANES[activePane].icon}</span>
                    <span className={cn(ICON, SHOWN_ON_HOVER)}>
                        <IconHideSidebar />
                    </span>
                </span>
            </TooltipTrigger>
            <TooltipContent>
                Hide sidebar
                <Kbd>{todaySidebarShortcutLabel()}</Kbd>
            </TooltipContent>
        </Tooltip>
    )
}
