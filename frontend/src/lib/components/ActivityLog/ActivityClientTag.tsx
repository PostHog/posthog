import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { activityClientLabel, isScoutClient } from 'lib/components/ActivityLog/activityClientLabel'

const SELF_REPORTED_TOOLTIP = 'Self-reported by the API client in the x-posthog-client request header'
const SCOUT_TOOLTIP = 'PostHog recognized this scout from the token its run used, so it is not self-reported'

export interface ActivityClientTagProps {
    client: string
}

export function ActivityClientTag({ client }: ActivityClientTagProps): JSX.Element {
    return (
        <Tooltip title={isScoutClient(client) ? SCOUT_TOOLTIP : SELF_REPORTED_TOOLTIP}>
            <LemonTag size="small" type="muted">
                via {activityClientLabel(client)}
            </LemonTag>
        </Tooltip>
    )
}
