import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { ConversationTurn, NodeSideContent } from '../types'
import { conversationalSideMessages } from './conversationalMessages'
import { ErrorCallout } from './ErrorCallout'
import { IOSection } from './IOSection'
import { ThreadBubble } from './ThreadBubble'

export interface ThreadTurnProps {
    turn: ConversationTurn
    isActive: boolean
    onSelectMessage: (sourceNodeId: string) => void
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
}

export function ThreadTurn({
    turn,
    isActive,
    onSelectMessage,
    matchingNodeIds = null,
    highlightQuery = null,
}: ThreadTurnProps): JSX.Element {
    const [showInternal, setShowInternal] = useState(false)
    const hiddenCount = [turn.input, turn.output]
        .flatMap(conversationalSideMessages)
        .filter((message) => message.isInternal).length

    const renderSide = (title: string, side: NodeSideContent): JSX.Element | JSX.Element[] => {
        if (side.kind === 'json') {
            return <IOSection key={title} title={title} value={side.value} highlightQuery={highlightQuery} />
        }
        return conversationalSideMessages(side)
            .filter((message) => showInternal || !message.isInternal)
            .map((message) => {
                const sourceNodeId = message.sourceNodeId
                return (
                    <ThreadBubble
                        key={message.id}
                        message={message}
                        onSelect={sourceNodeId ? () => onSelectMessage(sourceNodeId) : undefined}
                        isFaded={
                            matchingNodeIds !== null && sourceNodeId !== null && !matchingNodeIds.has(sourceNodeId)
                        }
                        highlightQuery={highlightQuery}
                    />
                )
            })
    }

    return (
        <div className={cn('flex flex-col gap-3', isActive && 'rounded-lg p-3 ring-1 ring-[var(--color-accent)]')}>
            {hiddenCount > 0 ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-center"
                    onClick={() => setShowInternal(!showInternal)}
                    data-attr="trace-view-toggle-hidden-messages"
                >
                    {showInternal ? 'Hide internal messages' : `Show ${pluralize(hiddenCount, 'internal message')}`}
                </LemonButton>
            ) : null}
            {renderSide('Input', turn.input)}
            {renderSide('Output', turn.output)}
            {turn.error ? <ErrorCallout message={turn.error} /> : null}
        </div>
    )
}
