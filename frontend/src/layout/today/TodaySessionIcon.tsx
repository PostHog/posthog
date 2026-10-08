import { IconChat } from '@posthog/icons'

import { todaySessionDot } from './todaySessionDot'
import { TodaySessionStatusDot } from './TodaySessionStatusDot'
import { TodayWorkItem } from './todayWorkItems'

/**
 * The one icon for a PostHog AI session or chat, wherever it shows: a chat bubble for a chat, and for a session
 * the status dot from PostHog Desktop's task rows.
 */
export function TodaySessionIcon({
    item,
    unread = false,
}: {
    item: Pick<TodayWorkItem, 'kind' | 'status' | 'runEnvironment'>
    unread?: boolean
}): JSX.Element {
    if (item.kind === 'chat') {
        return <IconChat className="text-muted-foreground" />
    }
    return <TodaySessionStatusDot dot={todaySessionDot(item, unread)} />
}
