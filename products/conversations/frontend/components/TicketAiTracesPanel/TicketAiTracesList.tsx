import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { PropertyFilterType } from '~/types'

import { TICKET_AI_TRACES_DATE_FROM, ticketAiTracesLogic } from './ticketAiTracesLogic'

export function TicketAiTracesList({ personId }: { personId: string }): JSX.Element {
    const logic = ticketAiTracesLogic({ personId })
    const { result, resultLoading } = useValues(logic)
    const { loadResult } = useActions(logic)

    const allTracesUrl = `${urls.aiObservabilityTraces()}?${new URLSearchParams({
        filters: JSON.stringify([{ type: PropertyFilterType.HogQL, key: `person_id = '${personId}'` }]),
        date_from: TICKET_AI_TRACES_DATE_FROM,
    })}`

    return (
        <div>
            {resultLoading && !result ? (
                <div className="text-muted-alt text-xs">Loading AI traces...</div>
            ) : !result ? (
                <div className="flex items-center justify-between gap-2 text-muted-alt text-xs">
                    Couldn't load AI traces.
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={loadResult}
                        loading={resultLoading}
                        data-attr="ticket-sidebar-ai-traces-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            ) : result.traces.length === 0 ? (
                <div className="text-muted-alt text-xs">No AI traces from this person in the last 30 days.</div>
            ) : (
                <div className="space-y-2 max-h-96 overflow-auto">
                    {result.traces.map((trace) => (
                        <Link
                            key={trace.id}
                            to={urls.aiObservabilityTrace(trace.id, { timestamp: trace.createdAt })}
                            className="block p-2 rounded border border-primary hover:bg-accent-3000 transition-colors hover:border-secondary"
                            data-attr="ticket-sidebar-ai-trace"
                        >
                            <div className="flex items-center justify-between gap-2 mb-1">
                                <span className="text-xs font-semibold truncate">{trace.traceName || trace.id}</span>
                                {!!trace.errorCount && (
                                    <LemonTag type="danger" size="small">
                                        {trace.errorCount === 1 ? '1 error' : `${trace.errorCount} errors`}
                                    </LemonTag>
                                )}
                            </div>
                            <div className="flex items-center justify-between gap-2 text-xs text-muted-alt">
                                <TZLabel time={trace.createdAt} />
                                {!!trace.totalCost && <span>{humanFriendlyCurrency(trace.totalCost, 4)}</span>}
                            </div>
                        </Link>
                    ))}
                </div>
            )}
            <div className="mt-2 pt-2 border-t flex justify-end">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    to={allTracesUrl}
                    data-attr="ticket-sidebar-ai-traces-see-all"
                >
                    See all AI traces →
                </LemonButton>
            </div>
        </div>
    )
}
