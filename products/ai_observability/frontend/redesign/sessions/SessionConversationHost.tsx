import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import type { SessionListItemApi, SessionPreviewApi, TracePersonApi } from '../../generated/api.schemas'
import type { TraceCellLoad } from '../shared/cellLoads'
import { TraceDrawerRowsSync } from '../trace/TraceDrawerRowsHost'
import { SessionConversation } from './components/SessionConversation'
import { SessionHeader, SessionListNavigation } from './components/SessionHeader'
import { SESSION_TURNS_LIST, sessionConversationLogic } from './sessionConversationLogic'
import { sessionConversationOptionsLogic } from './sessionConversationOptionsLogic'

export interface SessionConversationHostProps {
    sessionId: string
    /** The time the session's link carries, so an older session still reads. */
    timestamp: string | null
    /** The session's facts for the header, or null while they load. The conversation reads without them. */
    session: SessionListItemApi | null
    title: TraceCellLoad<SessionPreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    /** A turn to open the conversation on, read when the conversation opens. */
    aroundTraceId: string | null
    listNavigation?: SessionListNavigation
    /** Reads the title and the person again, where the session is not beside a list whose reload does. */
    onRetryDetails?: () => void
}

export function SessionConversationHost({
    sessionId,
    timestamp,
    session,
    title,
    person,
    aroundTraceId,
    listNavigation,
    onRetryDetails,
}: SessionConversationHostProps): JSX.Element {
    const logic = sessionConversationLogic({ sessionId, timestamp, aroundTraceId })
    const { status, turns, openTraceId, rows, olderEdge, newerEdge } = useValues(logic)
    const { loadOlder, loadNewer, reload, openTurn, retrySides } = useActions(logic)
    const { conversationOnly } = useValues(sessionConversationOptionsLogic)
    const { setConversationOnly } = useActions(sessionConversationOptionsLogic)
    const onSelectMessage = useCallback(
        (sourceNodeId: string, turnId: string) => openTurn(turnId, sourceNodeId),
        [openTurn]
    )

    return (
        <div className="flex h-full min-h-0 flex-col">
            <SessionHeader
                sessionId={sessionId}
                item={session}
                title={title}
                person={person}
                conversationOnly={conversationOnly}
                onConversationOnlyChange={setConversationOnly}
                listNavigation={listNavigation}
                onRetryDetails={onRetryDetails}
            />
            <SessionConversation
                className="min-h-0 flex-1"
                status={status}
                turns={turns}
                activeTurnId={openTraceId}
                olderEdge={olderEdge}
                newerEdge={newerEdge}
                conversationOnly={conversationOnly}
                onSelectMessage={onSelectMessage}
                onLoadOlder={loadOlder}
                onLoadNewer={loadNewer}
                onReload={reload}
                onRetrySides={retrySides}
            />
            <TraceDrawerRowsSync
                listId={SESSION_TURNS_LIST}
                rows={rows}
                rowsBefore={olderEdge !== 'end'}
                rowsAfter={newerEdge !== 'end'}
            />
        </div>
    )
}
