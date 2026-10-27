import { useValues } from 'kea'

import { cn } from '@posthog/quill'

import { notificationsPaneLogic } from 'products/notifications/frontend/pane/notificationsPaneLogic'
import { notificationsRailSignal } from 'products/notifications/frontend/pane/notificationsRailSignal'

import { TODAY_PANES } from './todayRailItems'

export function TodayNotificationsTab({
    active,
    onClick,
    className,
}: {
    active: boolean
    onClick: () => void
    className: string
}): JSX.Element {
    const { summary } = useValues(notificationsPaneLogic)
    const signal = notificationsRailSignal(summary)
    const { label, icon } = TODAY_PANES.notifications
    return (
        <button
            type="button"
            aria-current={active ? 'page' : undefined}
            aria-label={signal.ariaLabel}
            data-attr="today-rail-notifications"
            onClick={onClick}
            className={cn(className, 'relative', active ? 'bg-fill-selected text-foreground' : 'text-muted-foreground')}
        >
            {icon}
            {signal.severity !== 'none' && (
                <span
                    aria-hidden
                    className={cn(
                        'absolute top-1.5 right-1/4 size-2 rounded-full',
                        signal.severity === 'critical' ? 'bg-[var(--destructive-foreground)]' : 'bg-[var(--primary)]'
                    )}
                />
            )}
            <span className="max-w-full truncate">{label}</span>
        </button>
    )
}
