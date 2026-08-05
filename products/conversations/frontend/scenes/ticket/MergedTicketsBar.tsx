import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu } from '@posthog/lemon-ui'

import type { MergedTicketSummary } from '../../types'
import { supportTicketSceneLogic } from './supportTicketSceneLogic'

function ColorDot({ color }: { color?: string }): JSX.Element {
    return <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
}

/** Best-available human label for a merged ticket: its email subject or last message preview. */
function mergedTicketSubject(ticket: MergedTicketSummary): string | undefined {
    return ticket.email_subject || ticket.last_message_text || undefined
}

/** Header shown on a ticket that has other tickets merged into it. Lists the merged tickets
 * (rule 3) and lets the user interleave their messages into the conversation (rule 4). */
export function MergedTicketsBar(): JSX.Element | null {
    const { ticket, mergedTickets, visibleMergedTicketIds, ticketColorById } = useValues(supportTicketSceneLogic)
    const { setMergedTicketVisibility, showAllMergedTickets, hideAllMergedTickets } =
        useActions(supportTicketSceneLogic)

    if (!ticket || mergedTickets.length === 0) {
        return null
    }

    const visible = new Set(visibleMergedTicketIds)
    const allVisible = mergedTickets.every((t: MergedTicketSummary) => visible.has(t.id))

    return (
        <div className="flex items-center flex-wrap gap-2 rounded border bg-surface-secondary px-3 py-2">
            <span className="text-xs font-semibold text-muted-alt">Merged into this ticket:</span>
            {mergedTickets.map((t: MergedTicketSummary) => {
                const subject = mergedTicketSubject(t)
                return (
                    <LemonButton
                        key={t.id}
                        size="xsmall"
                        type={visible.has(t.id) ? 'primary' : 'secondary'}
                        onClick={() => setMergedTicketVisibility(t.id, !visible.has(t.id))}
                        tooltip={
                            <span>
                                {subject ? `${subject} · ` : ''}
                                {visible.has(t.id) ? 'Hide these messages' : 'Show these messages in the conversation'}
                            </span>
                        }
                    >
                        <span className="flex items-center gap-1.5 max-w-60">
                            <ColorDot color={ticketColorById[t.id]} />
                            <span className="shrink-0">#{t.ticket_number}</span>
                            {subject && <span className="truncate text-muted-alt">{subject}</span>}
                        </span>
                    </LemonButton>
                )
            })}
            <LemonMenu
                items={[
                    {
                        label: allVisible ? 'Hide all' : 'Show all',
                        onClick: () => (allVisible ? hideAllMergedTickets() : showAllMergedTickets()),
                    },
                    {
                        title: 'Show in conversation',
                        items: mergedTickets.map((t: MergedTicketSummary) => {
                            const subject = mergedTicketSubject(t)
                            return {
                                label: (
                                    <LemonCheckbox
                                        checked={visible.has(t.id)}
                                        onChange={(checked) => setMergedTicketVisibility(t.id, checked)}
                                        label={
                                            <span className="flex items-center gap-1.5">
                                                <span className="shrink-0">#{t.ticket_number}</span>
                                                {subject && (
                                                    <span className="truncate max-w-60 text-muted-alt">{subject}</span>
                                                )}
                                            </span>
                                        }
                                        fullWidth
                                    />
                                ),
                            }
                        }),
                    },
                ]}
            >
                <LemonButton size="xsmall" type="secondary" sideIcon={<IconChevronDown />}>
                    Show messages
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
