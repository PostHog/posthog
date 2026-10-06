import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todayShellLogic } from './todayShellLogic'

export function TodayNewChatButton(): JSX.Element {
    const { location } = useValues(router)
    const { phoneLayout } = useValues(todayShellLogic)
    const starting = location.pathname.endsWith(urls.taskNewSession())

    return (
        <Button
            variant="outline"
            size={phoneLayout ? 'default' : 'sm'}
            className="-me-2"
            render={<LinkPrimitive to={urls.taskNewSession()} />}
            aria-current={starting ? 'page' : undefined}
            data-attr="today-new-chat-header"
        >
            <IconPlus />
            New chat
        </Button>
    )
}
