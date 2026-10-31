import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { todayShellLogic } from './todayShellLogic'

export function TodaySidebarPinButton(): JSX.Element | null {
    const { sidebarPinned, mobileLayout } = useValues(todayShellLogic)
    const { toggleSidebarPinned } = useActions(todayShellLogic)

    // The drawer always closes when a page opens, so pinning has no effect there.
    if (mobileLayout) {
        return null
    }

    return (
        <Tooltip disableHoverablePopup>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-sm"
                        className={cn(
                            'shrink-0 text-muted-foreground',
                            // Pinned is the default, so the pin hides until the header is hovered. Unpinned stays in view.
                            sidebarPinned &&
                                'opacity-0 transition-opacity duration-150 ease-[ease] group-hover/header:opacity-100 focus-visible:opacity-100 motion-reduce:transition-none'
                        )}
                        aria-label="Pin sidebar"
                        aria-pressed={sidebarPinned}
                        data-attr="today-pane-pin-sidebar"
                        onClick={toggleSidebarPinned}
                    />
                }
            >
                {sidebarPinned ? <IconPinFilled /> : <IconPin />}
            </TooltipTrigger>
            <TooltipContent>
                {sidebarPinned ? 'Unpin to hide the sidebar after you open a page' : 'Pin to keep the sidebar open'}
            </TooltipContent>
        </Tooltip>
    )
}
