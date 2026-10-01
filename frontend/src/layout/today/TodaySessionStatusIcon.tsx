import { IconChat, IconCloud, IconPinFilled, IconSpinner } from '@posthog/icons'

import { TodaySessionIconKind, todaySessionIcon } from './todaySessionIcon'
import { TodayWorkItem } from './todayWorkItems'

const ICONS: Record<TodaySessionIconKind, { label: string; icon: JSX.Element }> = {
    chat: { label: 'Chat', icon: <IconChat className="text-muted-foreground" /> },
    running: { label: 'Running', icon: <IconSpinner className="text-info-foreground motion-safe:animate-spin" /> },
    queued: { label: 'Queued', icon: <IconCloud className="text-muted-foreground motion-safe:animate-pulse" /> },
    completed: { label: 'Completed', icon: <IconCloud className="text-success-foreground" /> },
    failed: { label: 'Failed', icon: <IconCloud className="text-destructive-foreground" /> },
    stopped: { label: 'Stopped', icon: <IconCloud className="text-muted-foreground" /> },
    pinned: { label: 'Pinned', icon: <IconPinFilled className="text-foreground" /> },
    session: { label: 'Session', icon: <IconCloud className="text-muted-foreground" /> },
}

export function TodaySessionStatusIcon({ item, pinned }: { item: TodayWorkItem; pinned: boolean }): JSX.Element {
    const { label, icon } = ICONS[todaySessionIcon(item, pinned)]
    return (
        <span role="img" aria-label={label} className="flex">
            {icon}
        </span>
    )
}
