import { useActions } from 'kea'

import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { IconHideSidebar, todaySidebarShortcutLabel } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

/** Hides the sidebar from its own title row. The scene header then shows the pane title to open it again. */
export function TodaySidebarCollapseButton(): JSX.Element {
    const { toggleSidebarFrom } = useActions(todayShellLogic)

    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        className="-ms-2 shrink-0 text-muted-foreground"
                        aria-label="Hide sidebar"
                        data-attr="today-pane-hide-sidebar"
                        onClick={() => toggleSidebarFrom('pane_header')}
                    />
                }
            >
                <IconHideSidebar />
            </TooltipTrigger>
            <TooltipContent>
                Hide sidebar
                <Kbd>{todaySidebarShortcutLabel()}</Kbd>
            </TooltipContent>
        </Tooltip>
    )
}
