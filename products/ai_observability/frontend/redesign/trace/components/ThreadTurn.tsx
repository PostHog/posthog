import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { ConversationTurn } from '../types'
import { conversationalMessages } from './conversationalMessages'
import { ThreadBubble } from './ThreadBubble'

export interface ThreadTurnProps {
    turn: ConversationTurn
    isActive: boolean
    onSelectMessage: (sourceNodeId: string) => void
}

export function ThreadTurn({ turn, isActive, onSelectMessage }: ThreadTurnProps): JSX.Element {
    const [showInternal, setShowInternal] = useState(false)
    const conversational = conversationalMessages(turn.messages)
    const hiddenCount = conversational.filter((message) => message.isInternal).length
    const visible = showInternal ? conversational : conversational.filter((message) => !message.isInternal)

    return (
        <div className={cn('flex flex-col gap-3', isActive && 'rounded-lg p-3 ring-1 ring-[var(--color-accent)]')}>
            {visible.map((message) => {
                const sourceNodeId = message.sourceNodeId
                return (
                    <ThreadBubble
                        key={message.id}
                        message={message}
                        onSelect={sourceNodeId ? () => onSelectMessage(sourceNodeId) : undefined}
                    />
                )
            })}
            {hiddenCount > 0 ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-center"
                    onClick={() => setShowInternal(!showInternal)}
                    data-attr="trace-view-toggle-hidden-messages"
                >
                    {showInternal ? 'Hide hidden messages' : `Show ${pluralize(hiddenCount, 'hidden message')}`}
                </LemonButton>
            ) : null}
        </div>
    )
}
