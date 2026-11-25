import { useActions, useValues } from 'kea'

import { ListEmptyState } from '../lists/components/ListEmptyState'
import { ListErrorState } from '../lists/components/ListErrorState'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { SessionConversationHost } from './SessionConversationHost'
import { SESSION_TURNS_LIST } from './sessionConversationLogic'
import { sessionPageLogic } from './sessionPageLogic'

// pinned: autocapture dashboards and tests select the page and its controls by this value and its suffixes
const DATA_ATTR = 'ai-observability-session-page'

export interface SessionPageHostProps {
    sessionId: string
}

export function SessionPageHost({ sessionId }: SessionPageHostProps): JSX.Element {
    const logic = sessionPageLogic({ sessionId })
    const { status, session, timestamp, title, person, sessionsHref } = useValues(logic)
    const { reload } = useActions(logic)
    const { openTraceId } = useValues(traceDrawerLogic({ listId: SESSION_TURNS_LIST }))

    const content = (): JSX.Element => {
        if (status === 'not_found') {
            return (
                <ListEmptyState
                    title="Session not found"
                    description="Check the link, or pick a session from the sessions list."
                    action={{
                        label: 'Go to sessions',
                        to: sessionsHref,
                        'data-attr': `${DATA_ATTR}-go-to-sessions`,
                    }}
                />
            )
        }
        if (status === 'failed') {
            return (
                <ListErrorState
                    title="Couldn't load this session"
                    description="Try again. If it keeps happening, contact support."
                    retry={{ onClick: reload, 'data-attr': `${DATA_ATTR}-retry` }}
                />
            )
        }
        return (
            <SessionConversationHost
                key={sessionId}
                sessionId={sessionId}
                timestamp={timestamp}
                session={session}
                title={title}
                person={person}
                aroundTraceId={openTraceId}
                onRetryDetails={reload}
            />
        )
    }

    return (
        <>
            {/* The conversation scrolls on its own, so the page fills the height the scene has left. */}
            <div
                className="flex min-h-100 flex-1 flex-col rounded border border-primary bg-surface-primary"
                data-attr={DATA_ATTR}
            >
                {content()}
            </div>
            <TraceDrawerHost listId={SESSION_TURNS_LIST} />
        </>
    )
}
