import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { LemonButton, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { ticketAiTraceDetailLogic } from './ticketAiTraceDetailLogic'

// The message renderer and its provider-format normalizers stay out of the ticket scene's chunk until a trace is opened.
const ConversationDisplay = lazyWithRetry(() =>
    import('products/ai_observability/frontend/ConversationDisplay/ConversationDisplay').then((m) => ({
        default: m.ConversationDisplay,
    }))
)

function eventLabel(event: LLMTraceEvent): string {
    return event.properties.$ai_span_name || event.properties.$ai_model || event.event
}

export function TicketAiTraceDetail({ traceId, createdAt }: { traceId: string; createdAt: string }): JSX.Element {
    const logic = ticketAiTraceDetailLogic({ traceId, createdAt })
    const { traceDetail, traceDetailLoading, eventsToShow } = useValues(logic)
    const { loadTraceDetail } = useActions(logic)

    const fullTraceLink = (
        <div className="flex justify-end">
            <LemonButton
                type="tertiary"
                size="xsmall"
                to={urls.aiObservabilityTrace(traceId, { timestamp: createdAt })}
                data-attr="ticket-sidebar-ai-trace-open-full"
            >
                Open full trace →
            </LemonButton>
        </div>
    )

    if (traceDetailLoading && !traceDetail) {
        return <LemonSkeleton className="h-24" />
    }

    if (!traceDetail) {
        return (
            <div className="space-y-2">
                <div className="flex items-center justify-between gap-2 text-muted-alt text-xs">
                    Couldn't load this trace.
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={loadTraceDetail}
                        data-attr="ticket-sidebar-ai-trace-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
                {fullTraceLink}
            </div>
        )
    }

    return (
        <div className="space-y-2">
            {eventsToShow.length === 0 ? (
                <div className="text-muted-alt text-xs">This trace has no recorded inputs or outputs.</div>
            ) : (
                <LemonCollapse
                    multiple
                    size="small"
                    defaultActiveKeys={[eventsToShow[eventsToShow.length - 1].id]}
                    panels={eventsToShow.map((event) => ({
                        key: event.id,
                        className: 'p-2',
                        header: (
                            <span className="flex items-center gap-2 min-w-0">
                                <span className="truncate">{eventLabel(event)}</span>
                                {(event.properties.$ai_error || event.properties.$ai_is_error) && (
                                    <LemonTag type="danger" size="small">
                                        Error
                                    </LemonTag>
                                )}
                            </span>
                        ),
                        content: (
                            <Suspense fallback={<LemonSkeleton className="h-24" />}>
                                <ConversationDisplay
                                    eventProperties={event.properties}
                                    eventId={event.id}
                                    eventName={event.event}
                                    eventTimestamp={event.createdAt}
                                    embedded
                                />
                            </Suspense>
                        ),
                    }))}
                />
            )}
            {fullTraceLink}
        </div>
    )
}
