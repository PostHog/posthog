import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Conversation, ConversationStatus, ConversationType, ProductKey } from '~/types'

import { maxLogic } from './maxLogic'
import { formatConversationDate } from './utils'

export interface ConversationHistoryProps {
    sidePanel?: boolean
}

export function ConversationHistory({ sidePanel = false }: ConversationHistoryProps): JSX.Element {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxLogic)
    const { toggleConversationHistory, openConversation } = useActions(maxLogic)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    return (
        <div className="@container/chat-history flex flex-col gap-4 w-full self-center px-4 py-8 grow max-w-screen-lg">
            {conversationHistory.length > 0 ? (
                conversationHistory.map((conversation) => (
                    <ConversationCard
                        key={conversation.id}
                        conversation={conversation}
                        openConversation={openConversation}
                        sidePanel={sidePanel}
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
                        titleOverride="Start getting things done with PostHog AI"
                        description="PostHog AI is an agent that answers data questions, gets things done in UI, and provides insights from PostHog’s documentation."
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

interface ConversationCardProps {
    conversation: Conversation
    openConversation: (conversationId: string) => void
    sidePanel: boolean
}

function ConversationCard({ conversation, openConversation, sidePanel }: ConversationCardProps): JSX.Element {
    return (
        <Link
            className="p-4 flex flex-row bg-surface-primary rounded-lg gap-2 w-full min-h-14 items-center justify-between"
            to={combineUrl(urls.max(conversation.id), { from: 'history' }).url}
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
    )
}
