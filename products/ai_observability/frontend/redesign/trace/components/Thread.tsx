import { LemonSkeleton } from '@posthog/lemon-ui'

import { ConversationState } from '../types'
import { conversationalMessages } from './conversationalMessages'
import { ThreadTurn } from './ThreadTurn'

export interface ThreadProps {
    conversation: ConversationState
    onSelectMessage: (sourceNodeId: string) => void
}

export function Thread({ conversation, onSelectMessage }: ThreadProps): JSX.Element {
    if (conversation.status === 'loading') {
        return (
            <div className="flex flex-col gap-3" role="status" aria-busy="true" aria-label="Loading conversation">
                <LemonSkeleton className="h-10 w-2/3 self-end" />
                <LemonSkeleton className="h-24 w-4/5" />
                <LemonSkeleton className="h-10 w-1/2 self-end" />
            </div>
        )
    }
    const { turns, activeTurnId } = conversation
    if (turns.every((turn) => conversationalMessages(turn.messages).length === 0 && !turn.error)) {
        return (
            <p className="m-0 text-secondary">
                This trace has no conversation to show. Switch to Spans to see its steps.
            </p>
        )
    }
    return (
        <div className="flex flex-col gap-3">
            {turns.map((turn) => (
                <ThreadTurn
                    key={turn.id}
                    turn={turn}
                    isActive={turns.length > 1 && turn.id === activeTurnId}
                    onSelectMessage={onSelectMessage}
                />
            ))}
        </div>
    )
}
