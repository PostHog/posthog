import { Fragment } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { ConversationState } from '../types'
import { turnHasContent } from './conversationalMessages'
import { ErrorCallout } from './ErrorCallout'
import { SilenceDivider } from './SilenceDivider'
import { ThreadTurn } from './ThreadTurn'
import { silenceBefore } from './turnGaps'
import { useSearchHighlight } from './useSearchHighlight'

export interface ThreadProps {
    conversation: ConversationState
    onSelectMessage: (sourceNodeId: string, turnId: string) => void
    onRetryTurns?: () => void
    highlightQuery?: string | null
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    showTiming?: boolean
    conversationOnly?: boolean
    /** Shown when no turn has anything to show. */
    emptyMessage?: string
}

const TRACE_EMPTY_MESSAGE = 'This trace has no conversation to show. Switch to Spans to see its steps.'

export function Thread({
    conversation,
    onSelectMessage,
    onRetryTurns,
    highlightQuery = null,
    matchingNodeIds = null,
    showTiming = false,
    conversationOnly = false,
    emptyMessage = TRACE_EMPTY_MESSAGE,
}: ThreadProps): JSX.Element {
    const highlightRef = useSearchHighlight(highlightQuery)
    if (conversation.status === 'loading') {
        return (
            <div className="flex flex-col gap-3" role="status" aria-busy="true" aria-label="Loading conversation">
                <LemonSkeleton className="h-10 w-2/3 self-end" />
                <LemonSkeleton className="h-24 w-4/5" />
                <LemonSkeleton className="h-10 w-1/2 self-end" />
            </div>
        )
    }
    if (conversation.status === 'error') {
        return <ErrorCallout message={conversation.message} />
    }
    const { turns, activeTurnId } = conversation
    if (turns.every((turn) => !turnHasContent(turn) && !turn.error && !turn.pending && !turn.missingReasons)) {
        return <p className="m-0 text-secondary">{emptyMessage}</p>
    }
    return (
        <div className="flex flex-col gap-3" ref={highlightRef}>
            {turns.map((turn, index) => {
                const silenceMs = showTiming ? silenceBefore(turns[index - 1] ?? null, turn) : null
                return (
                    <Fragment key={turn.id}>
                        {silenceMs !== null ? <SilenceDivider silenceMs={silenceMs} /> : null}
                        <ThreadTurn
                            turn={turn}
                            isActive={turns.length > 1 && turn.id === activeTurnId}
                            onSelectMessage={onSelectMessage}
                            onRetry={onRetryTurns}
                            matchingNodeIds={matchingNodeIds}
                            highlightQuery={highlightQuery}
                            showTiming={showTiming}
                            conversationOnly={conversationOnly}
                        />
                    </Fragment>
                )
            })}
        </div>
    )
}
