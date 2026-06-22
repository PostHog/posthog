import { useActions, useValues } from 'kea'

import { IconArchive, IconChevronRight } from '@posthog/icons'

import { NotificationActionButton, ReadToggleIcon } from 'lib/components/NotificationsMenu/NotificationActionButton'
import { NotificationRow } from 'lib/components/NotificationsMenu/NotificationRow'
import { getNotificationIcon } from 'lib/components/NotificationsMenu/notificationToasts'
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
    const { expandedGroupKeys, loadingGroupKeys } = useValues(sidePanelNotificationsLogic)
    const { toggleGroupExpanded, loadGroupChildren, loadArchivedGroupChildren, toggleGroupRead, archiveGroup } =
        useActions(sidePanelNotificationsLogic)
    const isExpanded = expandedGroupKeys.has(group.group_key)
    const isLoading = loadingGroupKeys.has(group.group_key)

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
                className={`group/row flex items-start gap-2.5 p-2 rounded cursor-pointer transition-colors ${
                    allRead ? 'hover:bg-fill-highlight-100' : 'bg-fill-highlight-50 hover:bg-fill-highlight-100'
                }`}
                onClick={handleExpand}
            >
                <div className="shrink-0 mt-0.5">{getNotificationIcon(group.representative.notification_type)}</div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-1">
                        <span className={`text-xs leading-snug ${allRead ? 'text-secondary' : 'font-semibold'}`}>
                            {group.representative.title}
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                            <span className="text-[10px] text-muted bg-fill-highlight-100 px-1.5 py-px rounded">
                                {group.count}
                            </span>
                            {!readOnly && (
                                <NotificationActionButton
                                    className="group/read"
                                    tooltip={allRead ? 'Mark group as unread' : 'Mark group as read'}
                                    onClick={handleToggleRead}
                                    icon={<ReadToggleIcon read={allRead} />}
                                />
                            )}
                            {!readOnly && (
                                <div className="ml-1 min-w-[26px] min-h-[26px] flex">
                                    {group.has_archivable && (
                                        <NotificationActionButton
                                            icon={<IconArchive className="size-4" />}
                                            tooltip="Archive group"
                                            onClick={handleArchive}
                                            tone="danger"
                                        />
                                    )}
                                </div>
                            )}
                            <NotificationActionButton
                                icon={
                                    <IconChevronRight
                                        className={`size-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                    />
                                }
                                ariaLabel={isExpanded ? 'Collapse group' : 'Expand group'}
                                onClick={handleExpand}
                            />
                        </div>
                    </div>
                    <div className="text-xs text-secondary mt-0.5 line-clamp-1">
                        {group.count} notifications · latest {dayjs(group.last_seen).fromNow()}
                    </div>
                </div>
            </div>
            {isExpanded && (
                <div className="pl-6 pr-1 flex flex-col gap-px border-l-2 border-fill-highlight-100 ml-3 my-1">
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
