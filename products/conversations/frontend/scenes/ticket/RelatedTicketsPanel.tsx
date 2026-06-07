import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { RelatedTicketApi } from '../../generated/api.schemas'

const CONVERSATIONS_SOURCE = 'conversations'

function sourceLabel(source: string): string {
    if (source === CONVERSATIONS_SOURCE) {
        return 'Support'
    }
    return source.charAt(0).toUpperCase() + source.slice(1)
}

function statusTagType(status: string): 'success' | 'primary' | 'default' {
    if (status === 'resolved' || status === 'closed') {
        return 'success'
    }
    if (status === 'new' || status === 'open') {
        return 'primary'
    }
    return 'default'
}

function RelatedTicketRow({ ticket }: { ticket: RelatedTicketApi }): JSX.Element {
    const isInternal = ticket.source === CONVERSATIONS_SOURCE
    const internalTo = ticket.ticket_number != null ? urls.supportTicketDetail(ticket.ticket_number) : undefined
    const linkProps = isInternal
        ? { to: internalTo }
        : ticket.url
          ? { to: ticket.url, target: '_blank' as const }
          : undefined

    const body = (
        <>
            <div className="flex items-center justify-between gap-2 mb-1">
                <span className="flex items-center gap-1 min-w-0">
                    <LemonTag type="muted">{sourceLabel(ticket.source)}</LemonTag>
                    {ticket.ticket_number != null && (
                        <span className="font-mono text-xs text-muted-alt">#{ticket.ticket_number}</span>
                    )}
                </span>
                <span className="flex items-center gap-1 shrink-0">
                    <LemonTag type={statusTagType(ticket.status)}>
                        {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                    </LemonTag>
                    {!isInternal && ticket.url && <IconExternal className="text-muted-alt" />}
                </span>
            </div>
            <div className="text-xs text-default line-clamp-2 mb-1">{ticket.title}</div>
            {ticket.last_activity && (
                <div className="text-xs text-muted-alt">Last activity {dayjs(ticket.last_activity).fromNow()}</div>
            )}
        </>
    )

    if (!linkProps) {
        return (
            <div className="block p-2 mb-2 rounded border border-primary opacity-75" aria-disabled>
                {body}
            </div>
        )
    }

    return (
        <Link
            {...linkProps}
            className="block p-2 mb-2 rounded border border-primary hover:bg-accent-3000 transition-colors hover:border-secondary"
        >
            {body}
        </Link>
    )
}

export function RelatedTicketsPanel({
    relatedTickets,
    relatedTicketsLoading,
}: {
    relatedTickets: RelatedTicketApi[]
    relatedTicketsLoading: boolean
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_RELATED_TICKETS]) {
        return null
    }

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'related-tickets',
                    header: (
                        <>
                            Related tickets
                            {relatedTickets.length > 0 && (
                                <span className="text-muted-alt font-normal ml-1">({relatedTickets.length})</span>
                            )}
                        </>
                    ),
                    content: (
                        <div className="space-y-2">
                            {relatedTicketsLoading ? (
                                <div className="text-muted-alt text-xs">Loading related tickets...</div>
                            ) : relatedTickets.length === 0 ? (
                                <div className="text-muted-alt text-xs">No related tickets found</div>
                            ) : (
                                <div className="space-y-2 max-h-96 overflow-auto">
                                    {relatedTickets.map((ticket) => (
                                        <RelatedTicketRow key={`${ticket.source}:${ticket.id}`} ticket={ticket} />
                                    ))}
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
