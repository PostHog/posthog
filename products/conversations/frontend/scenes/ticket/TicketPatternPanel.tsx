import { useValues } from 'kea'

import { LemonCollapse, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { TicketPatternSeverityTag } from '../../components/TicketPatterns/TicketPatternSeverityTag'
import { ticketPatternPanelLogic } from './ticketPatternPanelLogic'

interface TicketPatternPanelProps {
    ticketId: string
}

export function TicketPatternPanel({ ticketId }: TicketPatternPanelProps): JSX.Element | null {
    const { patternsEnabled, patterns, patternsLoading } = useValues(ticketPatternPanelLogic({ ticketId }))

    if (!patternsEnabled || (!patternsLoading && patterns.length === 0)) {
        return null
    }

    const content = patternsLoading ? (
        <div className="flex items-center gap-2 text-muted text-sm">
            <Spinner /> Checking for related tickets
        </div>
    ) : (
        <ul className="flex flex-col gap-2">
            {patterns.map((pattern) => (
                <li key={pattern.id} className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <TicketPatternSeverityTag severity={pattern.severity} />
                        <span className="font-medium">{pattern.title}</span>
                    </div>
                    <div className="text-sm text-muted">
                        This ticket is one of <span translate="no">{pattern.ticket_count}</span> from{' '}
                        <span translate="no">{pattern.requester_count}</span>{' '}
                        <span>{pattern.requester_count === 1 ? 'customer' : 'customers'}</span>
                        {pattern.status === 'open' ? ' that nobody has reviewed yet.' : '.'}{' '}
                        <Link to={urls.supportPatterns(pattern.status)}>See the pattern</Link>
                    </div>
                </li>
            ))}
        </ul>
    )

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="ticket-patterns"
            panels={[{ key: 'ticket-patterns', header: 'Similar tickets right now', content }]}
        />
    )
}
