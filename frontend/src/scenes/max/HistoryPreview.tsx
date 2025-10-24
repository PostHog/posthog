import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ConversationStatus, ConversationType } from '~/types'

import { maxLogic } from './maxLogic'
import { formatConversationDate } from './utils'

interface HistoryPreviewProps {
    sidePanel?: boolean
}

export function HistoryPreview({ sidePanel = false }: HistoryPreviewProps): JSX.Element | null {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxLogic)
    const { toggleConversationHistory, openConversation } = useActions(maxLogic)

    // No need to render if we do not have any conversations to show.
    if (!conversationHistory.length) {
        return null
    }

    return (
        <div className="max-w-120 w-full self-center flex flex-col gap-2 min-h-[6rem]">
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
                        className="text-sm flex items-center gap-2 text-primary hover:text-accent-hover active:text-accent-active justify-between"
                        to={urls.max(conversation.id)}
                        onClick={(e) => {
                            if (sidePanel) {
                                e.preventDefault()
                                openConversation(conversation.id)
                            }
                        }}
                    >
                        <div className="flex items-center gap-2">
                            <span className="flex-1 line-clamp-1">{conversation.title}</span>
                            {conversation.type === ConversationType.DeepResearch && <LemonTag>Deep research</LemonTag>}
                        </div>
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
