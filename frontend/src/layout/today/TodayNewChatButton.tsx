import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { aiShellLogic } from '~/layout/ai/aiShellLogic'

import { todayNewChatUrl } from './todayShellLogic'

export function TodayNewChatButton(): JSX.Element {
    const { location, searchParams } = useValues(router)
    const { effectivePhaiView } = useValues(aiShellLogic)
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
                        variant="outline"
                        render={<LinkPrimitive to={newChatUrl} />}
                        aria-current={starting ? 'page' : undefined}
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
