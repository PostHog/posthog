import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonSkeleton } from '@posthog/lemon-ui'

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
    const { status, session, title, person, sessionsHref } = useValues(logic)
    const { loadSession } = useActions(logic)
    const { openTraceId } = useValues(traceDrawerLogic({ listId: SESSION_TURNS_LIST }))
    const { push } = useActions(router)

    const content = (): JSX.Element => {
        if (session) {
            return (
                <SessionConversationHost
                    key={session.id}
                    session={session}
                    title={title}
                    person={person}
                    aroundTraceId={openTraceId}
                />
            )
        }
        if (status === 'not_found') {
            return (
                <ListEmptyState
                    title="Session not found"
                    description="It may be older than 30 days. Open it from the sessions list instead."
                    action={{
                        label: 'Go to sessions',
                        onClick: () => push(sessionsHref),
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
                    retry={{ onClick: loadSession, 'data-attr': `${DATA_ATTR}-retry` }}
                />
            )
        }
        return (
            <div className="flex flex-col gap-3 p-4" aria-busy="true">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="h-10 w-1/2 self-end" />
                <LemonSkeleton className="h-24 w-2/3" />
            </div>
        )
    }

    return (
        <>
            {/* The conversation scrolls on its own, so the page fills the window below the scene header. */}
            <div
                className="flex h-[calc(100vh-13.5rem)] min-h-100 flex-col rounded border border-primary bg-surface-primary"
                data-attr={DATA_ATTR}
            >
                {content()}
            </div>
            <TraceDrawerHost listId={SESSION_TURNS_LIST} />
        </>
    )
}
