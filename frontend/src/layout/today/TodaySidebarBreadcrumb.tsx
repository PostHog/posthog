import './TodayShell.scss'

import { useActions, useValues } from 'kea'

import { IconSidebarOpen } from '@posthog/icons'
import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TODAY_PANE_TITLES, todaySidebarShortcutLabel } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

/**
 * Shows the hidden sidebar's pane title before the scene title, and opens the sidebar again on click.
 * It renders nothing while the sidebar shows, and on phones, where the phone header opens the sidebar.
 */
export function TodaySidebarBreadcrumb(): JSX.Element | null {
    const { activePane, phoneLayout, sidebarVisible, todayRailEnabled } = useValues(todayShellLogic)
    const { toggleSidebarFrom } = useActions(todayShellLogic)

    if (!todayRailEnabled || phoneLayout || sidebarVisible) {
        return null
    }

    const title = TODAY_PANE_TITLES[activePane]

    return (
        <span className="TodaySidebarBreadcrumb -ms-2">
            <span className="TodaySidebarBreadcrumb__clip">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                className="text-muted-foreground"
                                aria-label={`Show ${title} sidebar`}
                                data-attr="today-scene-show-sidebar"
                                onClick={() => toggleSidebarFrom('scene_breadcrumb')}
                            />
                        }
                    >
                        <IconSidebarOpen />
                        {title}
                    </TooltipTrigger>
                    <TooltipContent>
                        Show sidebar
                        <Kbd>{todaySidebarShortcutLabel()}</Kbd>
                    </TooltipContent>
                </Tooltip>
            </span>
        </span>
    )
}
