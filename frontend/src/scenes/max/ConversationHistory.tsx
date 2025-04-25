import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

import { Conversation } from '~/types'

import { maxLogic } from './maxLogic'
import { getConversationUrl } from './utils'

export function ConversationHistory(): JSX.Element {
    const { location } = useValues(router)
    const { conversationHistory } = useValues(maxLogic)

    return (
        <div className="flex flex-col gap-4 w-full self-center px-4 py-8 grow">
            {conversationHistory.map((conversation) => (
                <ConversationCard
                    key={conversation.id}
                    conversation={conversation}
                    pathname={location.pathname}
                    search={location.search}
                />
            ))}
        </div>
    )
}

function ConversationCard({
    conversation,
    pathname,
    search,
}: {
    conversation: Conversation
    pathname: string
    search: string
}): JSX.Element {
    return (
        <Link
            className="p-4 flex flex-row bg-surface-primary rounded-lg gap-2 w-full"
            to={getConversationUrl({ pathname, search, conversationId: conversation.id })}
        >
            <span className="flex-1 line-clamp-1">{conversation.title}</span>
            <span className="text-secondary">
                {humanFriendlyDuration(dayjs().diff(dayjs(conversation.updated_at), 'seconds'))}
            </span>
        </Link>
    )
}
