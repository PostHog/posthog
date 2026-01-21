import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { ConversationStatus } from '~/types'

const MAX_RECENT_CONVERSATIONS = 5

export function RecentConversationsList({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxGlobalLogic)
    const { searchParams } = useValues(router)
    const currentConversationId = searchParams?.chat
    const recentConversations = conversationHistory.slice(0, MAX_RECENT_CONVERSATIONS)

    const [loadingStarted, setLoadingStarted] = useState(false)
    const [initialLoadComplete, setInitialLoadComplete] = useState(false)

    useEffect(() => {
        if (conversationHistoryLoading) {
            setLoadingStarted(true)
        } else if (loadingStarted && !initialLoadComplete) {
            setInitialLoadComplete(true)
        }
    }, [conversationHistoryLoading, loadingStarted, initialLoadComplete])

    // Show skeleton until initial load completes
    if (!initialLoadComplete) {
        return (
            <div className="flex flex-col gap-px">
                {Array.from({ length: MAX_RECENT_CONVERSATIONS }).map((_, i) => (
                    <WrappingLoadingSkeleton key={`skeleton-${i}`} fullWidth>
                        <ButtonPrimitive inert aria-hidden>
                            Loading...
                        </ButtonPrimitive>
                    </WrappingLoadingSkeleton>
                ))}
            </div>
        )
    }

    // After load: show empty state or content
    if (recentConversations.length === 0) {
        return (
            <div className="flex flex-col gap-px">
                <div className="text-muted text-xs px-2 py-1">No chats yet</div>
            </div>
        )
    }

    return (
        <div className={cn('flex flex-col gap-px')}>
            {recentConversations.map((conversation) => {
                const isActive = conversation.id === currentConversationId
                return (
                    <Link
                        key={conversation.id}
                        to={combineUrl(urls.ai(conversation.id), { from: 'history' }).url}
                        buttonProps={{
                            active: isActive,
                            menuItem: true,
                            // got to fix Link to stop being so powerful
                            className: '[--radius:4px]',
                        }}
                        tooltip={conversation.title}
                        tooltipPlacement="right"
                    >
                        <IconMessage className="size-4 text-secondary opacity-50" />
                        {!isCollapsed && (
                            <span className="flex-1 line-clamp-1 text-primary text-sm break-all">
                                {conversation.title}
                            </span>
                        )}
                        {conversation.status === ConversationStatus.InProgress && <Spinner className="h-3 w-3" />}
                    </Link>
                )
            })}
        </div>
    )
}
