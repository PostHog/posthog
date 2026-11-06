import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { PropertyFilterType } from '~/types'

import { TicketAiTraceDetail } from './TicketAiTraceDetail'
import { TICKET_AI_TRACES_DATE_FROM, ticketAiTracesLogic } from './ticketAiTracesLogic'

export function TicketAiTracesList({ personId }: { personId: string }): JSX.Element {
    const logic = ticketAiTracesLogic({ personId })
    const { result, resultLoading } = useValues(logic)
    const { loadResult } = useActions(logic)

    const allTracesUrl = `${urls.aiObservabilityTraces()}?${new URLSearchParams({
        filters: JSON.stringify([{ type: PropertyFilterType.HogQL, key: `person_id = '${personId}'` }]),
        date_from: TICKET_AI_TRACES_DATE_FROM,
        filter_test_accounts: 'false',
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
                <LemonCollapse
                    size="small"
                    panels={result.traces.map((trace) => ({
                        key: trace.id,
                        dataAttr: 'ticket-sidebar-ai-trace',
                        className: 'p-2',
                        header: (
                            <div className="flex-1 min-w-0 py-0.5">
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-xs font-semibold truncate">
                                        {trace.traceName || trace.id}
                                    </span>
                                    {!!trace.errorCount && (
                                        <LemonTag type="danger" size="small">
                                            {trace.errorCount === 1 ? '1 error' : `${trace.errorCount} errors`}
                                        </LemonTag>
                                    )}
                                </div>
                                <div className="flex items-center justify-between gap-2 text-xs text-muted-alt font-normal">
                                    <TZLabel time={trace.createdAt} />
                                    {!!trace.totalCost && <span>{humanFriendlyCurrency(trace.totalCost, 4)}</span>}
                                </div>
                            </div>
                        ),
                        content: <TicketAiTraceDetail traceId={trace.id} createdAt={trace.createdAt} />,
                    }))}
                />
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
