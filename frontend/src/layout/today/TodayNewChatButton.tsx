import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { todayNewChatUrl } from './todayShellLogic'

export function TodayNewChatButton(): JSX.Element {
    const { location, searchParams } = useValues(router)
    const { effectivePhaiView } = useValues(maxGlobalLogic)
    const newChatUrl = todayNewChatUrl(effectivePhaiView)
    // A legacy chat in progress also sits on `/ai`, with its id in `chat`.
    const starting = location.pathname.endsWith(newChatUrl) && !searchParams.chat && !searchParams.task

    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        render={<LinkPrimitive to={newChatUrl} />}
                        aria-current={starting ? 'page' : undefined}
                        className={cn('-me-2 text-muted-foreground', starting && 'bg-fill-selected text-foreground')}
                        aria-label="New chat"
                        data-attr="today-new-chat-header"
                    />
                }
            >
                <IconPlus />
            </TooltipTrigger>
            <TooltipContent>New chat</TooltipContent>
        </Tooltip>
    )
}
