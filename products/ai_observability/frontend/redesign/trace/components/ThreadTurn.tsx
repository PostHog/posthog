import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { ConversationTurn, NodeSideContent } from '../types'
import { conversationalSideMessages } from './conversationalMessages'
import { ErrorCallout } from './ErrorCallout'
import { IOSection } from './IOSection'
import { ThreadBubble } from './ThreadBubble'
import { TurnTiming } from './TurnTiming'

export interface ThreadTurnProps {
    turn: ConversationTurn
    isActive: boolean
    onSelectMessage: (sourceNodeId: string) => void
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
    matchingNodeIds = null,
    highlightQuery = null,
    showTiming = false,
    conversationOnly = false,
}: ThreadTurnProps): JSX.Element {
    const [showInternal, setShowInternal] = useState(false)
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
                        onSelect={sourceNodeId ? () => onSelectMessage(sourceNodeId) : undefined}
                        isFaded={
                            matchingNodeIds !== null && sourceNodeId !== null && !matchingNodeIds.has(sourceNodeId)
                        }
                        highlightQuery={highlightQuery}
                        // A user bubble leaves room on its left for the timing
                        className={showTiming && message.role === 'user' ? 'max-w-[76%]' : undefined}
                    />
                )
                return isTimed ? (
                    <div key={message.id} className="flex items-start justify-end gap-2">
                        <TurnTiming timestamp={turn.timestamp} waitMs={turn.waitMs} />
                        {bubble}
                    </div>
                ) : (
                    bubble
                )
            })
    }

    return (
        <div className={cn('flex flex-col gap-3', isActive && 'rounded-lg p-3 ring-1 ring-[var(--color-accent)]')}>
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
            {renderSide('Output', turn.output)}
            {turn.error ? <ErrorCallout message={turn.error} /> : null}
        </div>
    )
}
