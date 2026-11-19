import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ListEmptyState } from '../../lists/components/ListEmptyState'
import { ListErrorState } from '../../lists/components/ListErrorState'
import { Thread } from '../../trace/components/Thread'
import type { ConversationState } from '../../trace/types'
import type { ConversationEdge } from '../sessionConversationLogic'
import { useNearEnd } from './useNearEnd'

// pinned: autocapture dashboards and tests select the conversation and its controls by this value and its suffixes
const DATA_ATTR = 'ai-observability-session-conversation'

export interface SessionConversationProps {
    conversation: ConversationState
    olderEdge: ConversationEdge
    newerEdge: ConversationEdge
    conversationOnly: boolean
    onSelectMessage: (sourceNodeId: string, turnId: string) => void
    onLoadOlder: () => void
    onLoadNewer: () => void
    onRetryTurns: () => void
    onReload: () => void
    className?: string
}

export function SessionConversation({
    conversation,
    olderEdge,
    newerEdge,
    conversationOnly,
    onSelectMessage,
    onLoadOlder,
    onLoadNewer,
    onRetryTurns,
    onReload,
    className,
}: SessionConversationProps): JSX.Element {
    const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
    const endRef = useNearEnd(scroller, onLoadNewer, newerEdge === 'more')

    const content = (): JSX.Element => {
        if (conversation.status === 'error') {
            return (
                <ListErrorState
                    title={conversation.message}
                    description="Try again. If it keeps happening, contact support."
                    retry={{ onClick: onReload, 'data-attr': `${DATA_ATTR}-retry` }}
                />
            )
        }
        if (conversation.status === 'ready' && conversation.turns.length === 0) {
            return (
                <ListEmptyState
                    title="No turns to show"
                    description="None of this session's traces were found in its time range."
                />
            )
        }
        return (
            <>
                {olderEdge === 'end' ? null : olderEdge === 'failed' ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: onLoadOlder,
                            'data-attr': `${DATA_ATTR}-retry-older`,
                        }}
                    >
                        Couldn't load the earlier turns.
                    </LemonBanner>
                ) : (
                    <LemonButton
                        type="secondary"
                        size="small"
                        className="self-center"
                        onClick={onLoadOlder}
                        loading={olderEdge === 'loading'}
                        disabledReason={olderEdge === 'waiting' ? 'Turns are loading' : undefined}
                        data-attr={`${DATA_ATTR}-load-older`}
                    >
                        Show earlier turns
                    </LemonButton>
                )}
                <Thread
                    conversation={conversation}
                    onSelectMessage={onSelectMessage}
                    onRetryTurns={onRetryTurns}
                    showTiming
                    conversationOnly={conversationOnly}
                />
                {newerEdge === 'loading' ? (
                    <LemonSkeleton className="h-10 w-1/2 self-end" />
                ) : newerEdge === 'failed' ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: onLoadNewer,
                            'data-attr': `${DATA_ATTR}-retry-newer`,
                        }}
                    >
                        Couldn't load the next turns.
                    </LemonBanner>
                ) : null}
                <div ref={endRef} aria-hidden />
            </>
        )
    }

    return (
        <div ref={setScroller} className={cn('overflow-y-auto', className)} data-attr={DATA_ATTR}>
            <div className="flex flex-col gap-3 px-4 py-3">{content()}</div>
        </div>
    )
}
