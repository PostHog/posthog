import { useActions, useValues } from 'kea'

import type { SessionListItemApi, TracePersonApi, TracePreviewApi } from '../../generated/api.schemas'
import type { TraceCellLoad } from '../shared/cellLoads'
import { TraceDrawerRowsSync } from '../trace/TraceDrawerRowsHost'
import { SessionConversation } from './components/SessionConversation'
import { SessionHeader } from './components/SessionHeader'
import { SESSION_TURNS_LIST, sessionConversationLogic } from './sessionConversationLogic'
import { sessionConversationOptionsLogic } from './sessionConversationOptionsLogic'

export interface SessionConversationHostProps {
    session: SessionListItemApi
    title: TraceCellLoad<TracePreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    /** A turn to open the conversation on, read when the conversation opens. */
    aroundTraceId: string | null
}

/** The header and conversation of one session, whose turns the session's trace drawer steps through. */
export function SessionConversationHost({
    session,
    title,
    person,
    aroundTraceId,
}: SessionConversationHostProps): JSX.Element {
    const logic = sessionConversationLogic({
        sessionId: session.id,
        firstSeen: session.firstSeen,
        lastSeen: session.lastSeen,
        aroundTraceId,
    })
    const { turns, rows, olderEdge, newerEdge } = useValues(logic)
    const { loadOlder, loadNewer, retryTurns, reload, openTurn } = useActions(logic)
    const { conversationOnly } = useValues(sessionConversationOptionsLogic)
    const { setConversationOnly } = useActions(sessionConversationOptionsLogic)

    return (
        <div className="flex h-full min-h-0 flex-col">
            <SessionHeader
                item={session}
                title={title}
                person={person}
                conversationOnly={conversationOnly}
                onConversationOnlyChange={setConversationOnly}
            />
            <SessionConversation
                className="min-h-0 flex-1"
                conversation={turns}
                olderEdge={olderEdge}
                newerEdge={newerEdge}
                conversationOnly={conversationOnly}
                onSelectMessage={(sourceNodeId, turnId) => openTurn(turnId, sourceNodeId)}
                onLoadOlder={loadOlder}
                onLoadNewer={loadNewer}
                onRetryTurns={retryTurns}
                onReload={reload}
            />
            <TraceDrawerRowsSync listId={SESSION_TURNS_LIST} rows={rows} />
        </div>
    )
}
