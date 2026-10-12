import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todayShellLogic } from './todayShellLogic'

export function TodayNewChatButton(): JSX.Element {
    const { location } = useValues(router)
    const { phoneLayout } = useValues(todayShellLogic)
    const starting = location.pathname.endsWith(urls.taskNewSession())

    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size={phoneLayout ? 'icon-lg' : 'icon'}
                        render={<LinkPrimitive to={urls.taskNewSession()} />}
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
