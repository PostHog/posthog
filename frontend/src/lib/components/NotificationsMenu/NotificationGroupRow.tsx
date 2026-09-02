import { useActions, useValues } from 'kea'

import { IconArchive, IconChevronRight } from '@posthog/icons'

import {
    NotificationActionButton,
    ROW_ACTION_REVEAL_CLASSES,
} from 'lib/components/NotificationsMenu/NotificationActionButton'
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

export function NotificationGroupRow({
    group,
    onNavigate,
    readOnly = false,
}: {
    group: NotificationGroup
    onNavigate?: () => void
    readOnly?: boolean
}): JSX.Element {
    const { expandedGroupKeys, loadingGroupKeys, manuallyToggledIds, archivingEnabled } =
        useValues(sidePanelNotificationsLogic)
    const { toggleGroupExpanded, loadGroupChildren, loadArchivedGroupChildren, toggleGroupRead, archiveGroup } =
        useActions(sidePanelNotificationsLogic)
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
        return <NotificationRow notification={group.representative} onNavigate={onNavigate} readOnly={readOnly} />
    }

    const handleExpand = (e: React.MouseEvent): void => {
        e.stopPropagation()
        if (!group.full_children_loaded && !isExpanded) {
            if (readOnly) {
                void loadArchivedGroupChildren(group)
            } else {
                void loadGroupChildren(group)
            }
        }
        toggleGroupExpanded(group.group_key)
    }

    const handleToggleRead = (e: React.MouseEvent): void => {
        e.stopPropagation()
        toggleGroupRead(group)
    }

    const handleArchive = (e: React.MouseEvent): void => {
        e.stopPropagation()
        archiveGroup(group)
    }

    const allRead = !group.has_unread

    return (
        <div className="flex flex-col">
            <div
                ref={autoMarkRef}
                className={`group/row relative flex items-start gap-2 p-2 rounded cursor-pointer transition-colors ${
                    allRead ? 'hover:bg-fill-highlight-100' : 'bg-fill-highlight-50 hover:bg-fill-highlight-100'
                }`}
                onClick={handleExpand}
            >
                <div className="flex-1 min-w-0">
                    <NotificationTitle
                        notificationType={group.representative.notification_type}
                        title={group.representative.title}
                    />
                    {/* The count already reads in this line, so the actions carry no badge. They sit in
                        flow at the end rather than pinned absolutely — reserving their width with
                        padding would truncate the summary while space was still free. */}
                    <div className="flex items-center gap-1 mt-2">
                        <div className="min-w-0 flex-1 text-xs text-secondary truncate">
                            {group.count} notifications · latest {dayjs(group.last_seen).fromNow()}
                        </div>
                        <div className="shrink-0 flex items-center gap-1">
                            {!readOnly && (
                                // Revealed as one unit, like a single row's cluster — a group's actions
                                // shouldn't sit louder in the list than the rows it contains
                                <div className={`flex items-center gap-1 ${ROW_ACTION_REVEAL_CLASSES}`}>
                                    {archivingEnabled && (
                                        <NotificationActionButton
                                            icon={<IconArchive className="size-4" />}
                                            tooltip="Archive group"
                                            onClick={handleArchive}
                                            tone="danger"
                                        />
                                    )}
                                    <NotificationReadToggle read={allRead} onToggle={handleToggleRead} target="group" />
                                </div>
                            )}
                            {/* Stays visible: it's the only hint the row expands */}
                            <button
                                className="shrink-0 flex size-5 items-center justify-center rounded text-secondary hover:bg-fill-highlight-200 hover:text-primary"
                                onClick={handleExpand}
                                aria-label={isExpanded ? 'Collapse group' : 'Expand group'}
                            >
                                <IconChevronRight
                                    className={`size-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            {isExpanded && (
                <div className="ml-3 pl-3 flex flex-col gap-1 border-l-2 border-fill-highlight-100 my-1">
                    {isLoading && !group.full_children_loaded && <div className="text-xs text-muted p-2">Loading…</div>}
                    {group.children.map((child) => (
                        <NotificationRow
                            key={child.id}
                            notification={child}
                            onNavigate={onNavigate}
                            readOnly={readOnly}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
