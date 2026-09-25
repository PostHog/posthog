import { ConversationTurn } from '../types'
import { conversationalMessages } from './conversationalMessages'
import { ThreadTurn } from './ThreadTurn'

export interface ThreadProps {
    turns: ConversationTurn[]
    activeTurnId: string | null
    onSelectMessage: (sourceNodeId: string) => void
}

export function Thread({ turns, activeTurnId, onSelectMessage }: ThreadProps): JSX.Element {
    if (turns.every((turn) => conversationalMessages(turn.messages).length === 0)) {
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
