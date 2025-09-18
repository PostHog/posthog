import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronLeft, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { userLogic } from 'scenes/userLogic'

import { Conversation, ConversationStatus, ConversationType, ProductKey } from '~/types'

import { maxLogic } from './maxLogic'
import { formatConversationDate, getConversationUrl } from './utils'

export interface ConversationHistoryProps {
    sidePanel?: boolean
}

export function ConversationHistory({ sidePanel = false }: ConversationHistoryProps): JSX.Element {
    const { location } = useValues(router)
    const { conversationHistory, conversationHistoryLoading } = useValues(maxLogic)
    const { toggleConversationHistory, startNewConversation } = useActions(maxLogic)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    return (
        <div className="@container/chat-history flex flex-col gap-4 w-full self-center px-4 py-8 grow max-w-screen-lg">
            {!sidePanel && (
                <div className="flex items-center gap-4 mb-4">
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        onClick={() => startNewConversation()}
                        tooltip="Go back to home"
                        tooltipPlacement="bottom"
                    />
                    <h2 className="text-xl font-bold mb-0">Chat history</h2>
                </div>
            )}
            {conversationHistory.length > 0 ? (
                conversationHistory.map((conversation) => (
                    <ConversationCard
                        key={conversation.id}
                        conversation={conversation}
                        pathname={location.pathname}
                        search={location.search}
                        includeHash={sidePanel}
                    />
                ))
            ) : conversationHistoryLoading ? (
                <>
                    <LemonSkeleton className="h-14" />
                    <LemonSkeleton className="h-14 opacity-80" />
                    <LemonSkeleton className="h-14 opacity-60" />
                    <LemonSkeleton className="h-14 opacity-40" />
                    <LemonSkeleton className="h-14 opacity-20" />
                    <LemonSkeleton className="h-14 opacity-10" />
                    <LemonSkeleton className="h-14 opacity-5" />
                </>
            ) : (
                <div className="flex items-center flex-1">
                    <ProductIntroduction
                        isEmpty
                        productName="Max"
                        productKey={ProductKey.MAX}
                        thingName="chat"
                        titleOverride="Start chatting with Max"
                        description="Max is an AI product analyst in PostHog that answers data questions, gets things done in UI, and provides insights from PostHog’s documentation."
                        docsURL="https://posthog.com/docs/data/max-ai"
                        actionElementOverride={
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => {
                                    updateHasSeenProductIntroFor(ProductKey.MAX)
                                    toggleConversationHistory()
                                }}
                            >
                                Send your first message
                            </LemonButton>
                        }
                    />
                </div>
            )}
        </div>
    )
}

function ConversationCard({
    conversation,
    pathname,
    search,
    includeHash,
}: {
    conversation: Conversation
    pathname: string
    search: string
    includeHash: boolean
}): JSX.Element {
    return (
        <Link
            className="p-4 flex flex-row bg-surface-primary rounded-lg gap-2 w-full min-h-14 items-center justify-between"
            to={getConversationUrl({ pathname, search, conversationId: conversation.id, includeHash })}
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
    )
}
