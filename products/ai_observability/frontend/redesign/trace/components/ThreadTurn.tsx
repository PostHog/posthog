import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { ConversationTurn, NodeSideContent } from '../types'
import { conversationalSideMessages, sideHasContent } from './conversationalMessages'
import { ErrorCallout } from './ErrorCallout'
import { IOSection } from './IOSection'
import { scrollIntoNearest } from './scrollIntoNearest'
import { ThreadBubble } from './ThreadBubble'
import { TurnSideMissingNotice } from './TurnSideMissingNotice'
import { TurnTiming } from './TurnTiming'

export interface ThreadTurnProps {
    turn: ConversationTurn
    isActive: boolean
    onSelectMessage: (sourceNodeId: string, turnId: string) => void
    onRetry?: () => void
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
    showTiming?: boolean
    conversationOnly?: boolean
}

export function ThreadTurn({
    turn,
    isActive,
    onSelectMessage,
    onRetry,
    matchingNodeIds = null,
    highlightQuery = null,
    showTiming = false,
    conversationOnly = false,
}: ThreadTurnProps): JSX.Element {
    const [showInternal, setShowInternal] = useState(false)
    const turnClassName = cn('flex flex-col gap-3', isActive && 'rounded-lg p-3 ring-1 ring-[var(--color-accent)]')
    const timing = showTiming ? <TurnTiming timestamp={turn.timestamp} waitMs={turn.waitMs} /> : null
    const errorCallout = turn.error ? <ErrorCallout message={turn.error} /> : null

    if (turn.pending === 'loading') {
        return (
            <div className={turnClassName} aria-busy="true">
                <div className="flex items-start justify-end gap-2">
                    {timing}
                    <LemonSkeleton className="h-10 w-1/2" />
                </div>
                <LemonSkeleton className="h-16 w-3/4" />
            </div>
        )
    }
    if (turn.pending === 'error') {
        return (
            <div className={turnClassName}>
                <LemonBanner
                    type="error"
                    action={
                        onRetry
                            ? { children: 'Try again', onClick: onRetry, 'data-attr': 'trace-view-thread-retry-turn' }
                            : undefined
                    }
                >
                    Couldn't load this turn's messages.
                </LemonBanner>
                {errorCallout}
            </div>
        )
    }

    const hiddenCount = [turn.input, turn.output]
        .flatMap(conversationalSideMessages)
        .filter((message) => message.isInternal).length
    const canShowInternal = showInternal && !conversationOnly
    const timedMessageId = showTiming
        ? (conversationalSideMessages(turn.input).find((message) => message.role === 'user' && !message.isInternal)
              ?.id ?? null)
        : null

    const renderSide = (title: string, side: NodeSideContent): JSX.Element | JSX.Element[] => {
        if (side.kind === 'json') {
            return <IOSection key={title} title={title} value={side.value} highlightQuery={highlightQuery} />
        }
        return conversationalSideMessages(side)
            .filter((message) => canShowInternal || !message.isInternal)
            .map((message) => {
                const sourceNodeId = message.sourceNodeId
                const isTimed = message.id === timedMessageId
                const bubble = (
                    <ThreadBubble
                        key={message.id}
                        message={message}
                        onSelect={sourceNodeId ? () => onSelectMessage(sourceNodeId, turn.id) : undefined}
                        isFaded={
                            matchingNodeIds !== null && sourceNodeId !== null && !matchingNodeIds.has(sourceNodeId)
                        }
                        highlightQuery={highlightQuery}
                        className={showTiming && message.role === 'user' ? 'max-w-[76%]' : undefined}
                    />
                )
                return isTimed ? (
                    // The timing sits in the room that the user bubble's narrower cap leaves on its left.
                    <div key={message.id} className="flex items-start justify-end gap-2">
                        {timing}
                        {bubble}
                    </div>
                ) : (
                    bubble
                )
            })
    }

    const renderMissing = (side: 'input' | 'output'): JSX.Element | null => {
        const reason = turn.missingReasons?.[side]
        if (!reason) {
            return null
        }
        const notice = (
            <TurnSideMissingNotice
                side={side}
                reason={reason}
                partial={sideHasContent(turn[side])}
                // A turn's id is its trace's, which is also the id of the trace's root step.
                onOpenTrace={() => onSelectMessage(turn.id, turn.id)}
            />
        )
        // With no user message to sit beside, the timing goes beside the notice.
        return side === 'input' && timing && timedMessageId === null ? (
            <div className="flex items-start justify-end gap-2">
                {timing}
                {notice}
            </div>
        ) : (
            notice
        )
    }

    return (
        // A turn grows when its messages arrive, so the active turn is brought into view only once they are in
        <div className={turnClassName} ref={isActive ? scrollIntoNearest : undefined}>
            {hiddenCount > 0 && !conversationOnly ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-center"
                    onClick={() => setShowInternal(!showInternal)}
                    data-attr="trace-view-toggle-hidden-messages"
                >
                    {canShowInternal ? 'Hide internal messages' : `Show ${pluralize(hiddenCount, 'internal message')}`}
                </LemonButton>
            ) : null}
            {renderSide('Input', turn.input)}
            {renderMissing('input')}
            {renderSide('Output', turn.output)}
            {renderMissing('output')}
            {errorCallout}
        </div>
    )
}
