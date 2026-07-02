import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'

import {
    NotificationReadToggle,
    NotificationRow,
    NotificationTitle,
} from 'lib/components/NotificationsMenu/NotificationRow'
import { useAutoMarkRead } from 'lib/components/NotificationsMenu/useAutoMarkRead'
import { dayjs } from 'lib/dayjs'

import {
    NotificationGroup,
    sidePanelNotificationsLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

function NotificationGroupControls({
    count,
    allRead,
    expanded,
    onToggleRead,
    onToggleExpand,
}: {
    count: number
    allRead: boolean
    expanded: boolean
    onToggleRead: (e: React.MouseEvent) => void
    onToggleExpand: (e: React.MouseEvent) => void
}): JSX.Element {
    return (
        <div className="shrink-0 flex items-center gap-1">
            <span className="text-[10px] text-muted bg-fill-highlight-100 px-1.5 py-px rounded">{count}</span>
            <NotificationReadToggle read={allRead} onToggle={onToggleRead} target="group" />
            <button
                className="shrink-0 flex size-5 items-center justify-center rounded text-secondary hover:bg-fill-highlight-200 hover:text-primary"
                onClick={onToggleExpand}
                aria-label={expanded ? 'Collapse group' : 'Expand group'}
            >
                <IconChevronRight className={`size-4 transition-transform ${expanded ? 'rotate-90' : ''}`} />
            </button>
        </div>
    )
}

export function NotificationGroupRow({
    group,
    onNavigate,
}: {
    group: NotificationGroup
    onNavigate?: () => void
}): JSX.Element {
    const { expandedGroupKeys, loadingGroupKeys, manuallyToggledIds } = useValues(sidePanelNotificationsLogic)
    const { toggleGroupExpanded, loadGroupChildren, toggleGroupRead } = useActions(sidePanelNotificationsLogic)
    const isExpanded = expandedGroupKeys.has(group.group_key)
    const isLoading = loadingGroupKeys.has(group.group_key)

    // Don't let a collapsed group's auto-mark undo a child the user deliberately toggled this session.
    const hasManualChild =
        manuallyToggledIds.has(group.representative.id) || group.children.some((c) => manuallyToggledIds.has(c.id))

    // Dwelling on a collapsed, unread group marks the whole group read. When expanded,
    // the individual child rows mark themselves read instead, so disarm here.
    const autoMarkRef = useAutoMarkRead(group.count > 1 && group.has_unread && !isExpanded && !hasManualChild, () =>
        toggleGroupRead(group)
    )

    if (group.count === 1) {
        return <NotificationRow notification={group.representative} onNavigate={onNavigate} />
    }

    const handleExpand = (e: React.MouseEvent): void => {
        e.stopPropagation()
        if (!group.full_children_loaded && !isExpanded) {
            void loadGroupChildren(group)
        }
        toggleGroupExpanded(group.group_key)
    }

    const handleToggleRead = (e: React.MouseEvent): void => {
        e.stopPropagation()
        toggleGroupRead(group)
    }

    const allRead = !group.has_unread

    return (
        <div className="flex flex-col">
            <div
                ref={autoMarkRef}
                className={`flex items-start gap-2 p-2 rounded cursor-pointer transition-colors ${
                    allRead ? 'hover:bg-fill-highlight-100' : 'bg-fill-highlight-50 hover:bg-fill-highlight-100'
                }`}
                onClick={handleExpand}
            >
                <div className="flex-1 min-w-0">
                    <NotificationTitle
                        notificationType={group.representative.notification_type}
                        title={group.representative.title}
                    />
                    <div className="text-xs text-secondary mt-2 line-clamp-1">
                        {group.count} notifications · latest {dayjs(group.last_seen).fromNow()}
                    </div>
                </div>
                <NotificationGroupControls
                    count={group.count}
                    allRead={allRead}
                    expanded={isExpanded}
                    onToggleRead={handleToggleRead}
                    onToggleExpand={handleExpand}
                />
            </div>
            {isExpanded && (
                <div className="ml-3 pl-3 flex flex-col gap-1 border-l-2 border-fill-highlight-100 my-1">
                    {isLoading && !group.full_children_loaded && <div className="text-xs text-muted p-2">Loading…</div>}
                    {group.children.map((child) => (
                        <NotificationRow key={child.id} notification={child} onNavigate={onNavigate} />
                    ))}
                </div>
            )}
        </div>
    )
}
