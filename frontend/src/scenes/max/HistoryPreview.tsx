import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { ConversationStatus } from '~/types'

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
        <div className="max-w-120 flex w-full flex-col gap-2 self-center">
            <div className="-mr-2 flex items-center justify-between gap-2">
                <h3 className="text-secondary mb-0 text-sm font-medium">Recent chats</h3>
                <LemonButton
                    size="small"
                    onClick={() => toggleConversationHistory()}
                    tooltip="Open chat history"
                    tooltipPlacement="bottom"
                >
                    View all
                </LemonButton>
            </div>
            {conversationHistoryLoading && !conversationHistory.length ? (
                <>
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                </>
            ) : (
                conversationHistory.slice(0, 3).map((conversation) => (
                    <Link
                        key={conversation.id}
                        className="text-primary hover:text-accent-hover active:text-accent-active flex items-center text-sm"
                        to={getConversationUrl({
                            pathname: location.pathname,
                            search: location.search,
                            conversationId: conversation.id,
                            includeHash: sidePanel,
                        })}
                    >
                        <span className="line-clamp-1 flex-1">{conversation.title}</span>
                        {conversation.status === ConversationStatus.InProgress ? (
                            <Spinner className="h-4 w-4" />
                        ) : (
                            <span className="text-secondary">{formatConversationDate(conversation.updated_at)}</span>
                        )}
                    </Link>
                ))
            )}
        </div>
    )
}
