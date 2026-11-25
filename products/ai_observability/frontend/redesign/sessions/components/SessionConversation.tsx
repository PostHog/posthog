import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ListEmptyState } from '../../lists/components/ListEmptyState'
import { ListErrorState } from '../../lists/components/ListErrorState'
import { Thread } from '../../trace/components/Thread'
import type { ConversationTurn } from '../../trace/types'
import type { ConversationEdge, ConversationStatus } from '../types'
import { useNearEnd } from './useNearEnd'

// pinned: autocapture dashboards and tests select the conversation and its controls by this value and its suffixes
const DATA_ATTR = 'ai-observability-session-conversation'

export interface SessionConversationProps {
    status: ConversationStatus
    turns: ConversationTurn[]
    /** The turn open in the trace drawer, if any. */
    activeTurnId: string | null
    olderEdge: ConversationEdge
    newerEdge: ConversationEdge
    conversationOnly: boolean
    onSelectMessage: (sourceNodeId: string, turnId: string) => void
    onLoadOlder: () => void
    onLoadNewer: () => void
    onReload: () => void
    onRetrySides: () => void
    className?: string
}

export function SessionConversation({
    status,
    turns,
    activeTurnId,
    olderEdge,
    newerEdge,
    conversationOnly,
    onSelectMessage,
    onLoadOlder,
    onLoadNewer,
    onReload,
    onRetrySides,
    className,
}: SessionConversationProps): JSX.Element {
    const [scroller, setScroller] = useState<HTMLDivElement | null>(null)
    const endRef = useNearEnd(scroller, onLoadNewer, newerEdge === 'more')

    const content = (): JSX.Element => {
        if (status === 'not_found') {
            return <ListEmptyState title="Session not found" description="Check the link, or pick another session." />
        }
        if (status === 'failed') {
            return (
                <ListErrorState
                    title="Couldn't load this session"
                    description="Try again. If it keeps happening, contact support."
                    retry={{ onClick: onReload, 'data-attr': `${DATA_ATTR}-retry` }}
                />
            )
        }
        // A page can hold no turn and still have turns before or after it, when the server leaves out turns it cannot
        // show. Only a session with no page left to read is empty.
        const noTurns = status === 'ready' && turns.length === 0
        if (noTurns && olderEdge === 'end' && newerEdge === 'end') {
            return (
                <ListEmptyState title="No turns to show" description="We couldn't find any traces for this session." />
            )
        }
        return (
            <>
                {olderEdge === 'end' ? null : olderEdge === 'failed' ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
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
                {noTurns ? null : (
                    <Thread
                        conversation={status === 'ready' ? { status, turns, activeTurnId } : { status: 'loading' }}
                        onSelectMessage={onSelectMessage}
                        showTiming
                        conversationOnly={conversationOnly}
                        emptyMessage="This session has no messages to show. Messages outside the retention period are no longer stored."
                        onRetrySides={onRetrySides}
                    />
                )}
                {newerEdge === 'loading' || (noTurns && newerEdge !== 'failed' && newerEdge !== 'end') ? (
                    <LemonSkeleton className="h-10 w-1/2 self-end" />
                ) : newerEdge === 'failed' ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
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
