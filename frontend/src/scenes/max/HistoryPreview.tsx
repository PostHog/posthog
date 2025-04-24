import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

import { SidePanelTab } from '~/types'

import { maxLogic } from './maxLogic'

export function HistoryPreview(): JSX.Element | null {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxLogic)

    if (!conversationHistory.length && !conversationHistoryLoading) {
        return null
    }

    return (
        <div className="max-w-120 w-full self-center flex flex-col gap-2">
            <h3 className="text-sm font-medium text-secondary">Past chats</h3>
            {conversationHistoryLoading ? (
                <>
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                </>
            ) : (
                conversationHistory.slice(0, 3).map((conversation) => (
                    <Link
                        key={conversation.id}
                        className="text-sm flex items-center text-primary hover:text-accent-hover active:text-accent-active"
                        to={`?conversation=${conversation.id}#panel=${SidePanelTab.Max}`}
                    >
                        <span className="flex-1 line-clamp-1">{conversation.title}</span>
                        <span className="text-secondary">
                            {humanFriendlyDuration(dayjs().diff(dayjs(conversation.updated_at), 'seconds'))}
                        </span>
                    </Link>
                ))
            )}
        </div>
    )
}
