import { useActions, useValues } from 'kea'

import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { IconShowSidebar, TODAY_PANES, todaySidebarShortcutLabel } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

/** The hidden sidebar's pane title as a button that opens the sidebar again. `QuillSceneTrail` decides when it shows. */
export function TodaySidebarBreadcrumb(): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { toggleSidebar } = useActions(todayShellLogic)
    const { title } = TODAY_PANES[activePane]

    return (
        <Tooltip disableHoverablePopup>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        className="-ms-2 shrink-0 text-muted-foreground"
                        aria-label={`Show ${title} sidebar`}
                        data-attr="today-scene-show-sidebar"
                        onClick={() => toggleSidebar('scene_breadcrumb')}
                    />
                }
            >
                {/* The hide button centers this icon 7.5px from its edge. This button pads it by 8px, so pull it back. */}
                <IconShowSidebar className="-ms-[0.5px]" />
                {/* A narrow scene keeps only the icon, so the scene's own name has room. */}
                <span className="@max-xl/main-content:hidden">{title}</span>
            </TooltipTrigger>
            <TooltipContent>
                Show sidebar
                <Kbd>{todaySidebarShortcutLabel()}</Kbd>
            </TooltipContent>
        </Tooltip>
    )
}
