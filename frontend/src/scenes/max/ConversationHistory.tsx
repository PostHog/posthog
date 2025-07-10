import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronLeft, IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { userLogic } from 'scenes/userLogic'

import { Conversation, ConversationStatus, ProductKey } from '~/types'

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
        <div className="@container/chat-history flex w-full max-w-screen-lg grow flex-col gap-4 self-center px-4 py-8">
            {!sidePanel && (
                <div className="mb-4 flex items-center gap-4">
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        onClick={() => startNewConversation()}
                        tooltip="Go back to home"
                        tooltipPlacement="bottom"
                    />
                    <h2 className="mb-0 text-xl font-bold">Chat history</h2>
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
                <div className="flex flex-1 items-center">
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
                                    updateHasSeenProductIntroFor(ProductKey.MAX, true)
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
            className="bg-surface-primary flex min-h-14 w-full flex-row items-center gap-2 rounded-lg p-4"
            to={getConversationUrl({ pathname, search, conversationId: conversation.id, includeHash })}
        >
            <span className="line-clamp-1 flex-1">{conversation.title}</span>
            {conversation.status === ConversationStatus.InProgress ? (
                <Spinner className="h-4 w-4" />
            ) : (
                <span className="text-secondary">{formatConversationDate(conversation.updated_at)}</span>
            )}
        </Link>
    )
}
