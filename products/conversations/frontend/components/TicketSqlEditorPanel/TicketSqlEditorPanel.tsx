import { LemonCollapse } from '@posthog/lemon-ui'

import { TicketSqlEditor } from './TicketSqlEditor'

export function TicketSqlEditorPanel({ personId, distinctId }: { personId: string; distinctId: string }): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'sql-editor',
                    header: 'SQL editor',
                    dataAttr: 'ticket-sidebar-sql-editor-toggle',
                    // The editor mounts Monaco, so it only loads once the panel is opened.
                    content: <TicketSqlEditor personId={personId} distinctId={distinctId} />,
                },
            ]}
        />
    )
}
