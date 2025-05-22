import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { maxLogic } from './maxLogic'
import { formatConversationDate, getConversationUrl } from './utils'

interface HistoryPreviewProps {
    sidePanel?: boolean
}

export function HistoryPreview({ sidePanel = false }: HistoryPreviewProps): JSX.Element | null {
    const { location } = useValues(router)
    const { conversationHistory, conversationHistoryLoading } = useValues(maxLogic)
    const { toggleConversationHistory } = useActions(maxLogic)

    if (!conversationHistory.length && !conversationHistoryLoading) {
        return null
    }

    return (
        <div className="w-full max-w-120 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 -mr-2">
                <h3 className="text-sm font-medium text-secondary mb-0">Recent chats</h3>
                <LemonButton
                    size="small"
                    onClick={() => toggleConversationHistory()}
                    tooltip="Open chat history"
                    tooltipPlacement="bottom"
                >
                    View all
                </LemonButton>
            </div>
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
                        to={getConversationUrl({
                            pathname: location.pathname,
                            search: location.search,
                            conversationId: conversation.id,
                            includeHash: sidePanel,
                        })}
                    >
                        <span className="flex-1 line-clamp-1">{conversation.title}</span>
                        <span className="text-secondary">{formatConversationDate(conversation.updated_at)}</span>
                    </Link>
                ))
            )}
        </div>
    )
}
