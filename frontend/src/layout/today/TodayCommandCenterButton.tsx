import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconApps } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function TodayCommandCenterButton(): JSX.Element {
    const { location } = useValues(router)
    const open = location.pathname.endsWith(urls.taskCommandCenter())

    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        render={<LinkPrimitive to={urls.taskCommandCenter()} />}
                        aria-current={open ? 'page' : undefined}
                        className={cn('text-muted-foreground', open && 'bg-fill-selected text-foreground')}
                        aria-label="Command center"
                        data-attr="today-command-center-header"
                    />
                }
            >
                <IconApps />
            </TooltipTrigger>
            <TooltipContent>Command center</TooltipContent>
        </Tooltip>
    )
}
