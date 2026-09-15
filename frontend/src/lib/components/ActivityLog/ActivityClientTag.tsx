import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { describeActivityClient } from 'lib/components/ActivityLog/activityClient'

export interface ActivityClientTagProps {
    client?: string | null
}

/** Names the API client, or the scout, behind one activity log row. */
export function ActivityClientTag({ client }: ActivityClientTagProps): JSX.Element | null {
    if (!client) {
        return null
    }
    const { label, tooltip } = describeActivityClient(client)
    return (
        <Tooltip title={tooltip}>
            <LemonTag size="small" type="muted">
                via {label}
            </LemonTag>
        </Tooltip>
    )
}
