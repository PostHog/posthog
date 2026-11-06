import { LemonCollapse } from '@posthog/lemon-ui'

import { TicketAiTracesList } from './TicketAiTracesList'

export function TicketAiTracesPanel({ personId }: { personId: string }): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'ai-traces',
                    header: 'AI traces',
                    dataAttr: 'ticket-sidebar-ai-traces-toggle',
                    // The list mounts its logic, so the traces query only runs once the panel is opened.
                    content: <TicketAiTracesList personId={personId} />,
                },
            ]}
        />
    )
}
