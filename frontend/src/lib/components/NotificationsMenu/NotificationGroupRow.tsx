import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { NotificationRow } from 'lib/components/NotificationsMenu/NotificationRow'
import { getNotificationIcon } from 'lib/components/NotificationsMenu/notificationToasts'
import { dayjs } from 'lib/dayjs'
import { IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'

import {
    NotificationGroup,
    sidePanelNotificationsLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

export function NotificationGroupRow({
    group,
    onNavigate,
}: {
    group: NotificationGroup
    onNavigate?: () => void
}): JSX.Element {
    const { expandedGroupKeys, loadingGroupKeys } = useValues(sidePanelNotificationsLogic)
    const { toggleGroupExpanded, loadGroupChildren, toggleGroupRead } = useActions(sidePanelNotificationsLogic)
    const isExpanded = expandedGroupKeys.has(group.group_key)
    const isLoading = loadingGroupKeys.has(group.group_key)

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
                className={`flex items-start gap-2.5 p-2 rounded cursor-pointer transition-colors ${
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
                            <Tooltip title={allRead ? 'Mark group as unread' : 'Mark group as read'}>
                                <button
                                    className="group/read min-w-[26px] min-h-[26px] flex items-center justify-center rounded hover:bg-fill-highlight-200 cursor-pointer"
                                    onClick={handleToggleRead}
                                >
                                    {allRead ? (
                                        <IconCheckCircle className="size-4 text-success" />
                                    ) : (
                                        <>
                                            <IconRadioButtonUnchecked className="size-4 text-muted opacity-40 group-hover/read:hidden" />
                                            <IconCheckCircle className="size-4 text-muted opacity-60 hidden group-hover/read:block" />
                                        </>
                                    )}
                                </button>
                            </Tooltip>
                            <button
                                className="min-w-[26px] min-h-[26px] flex items-center justify-center rounded hover:bg-fill-highlight-200 text-secondary hover:text-primary"
                                onClick={handleExpand}
                                aria-label={isExpanded ? 'Collapse group' : 'Expand group'}
                            >
                                <IconChevronRight
                                    className={`size-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                />
                            </button>
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
                        <NotificationRow key={child.id} notification={child} onNavigate={onNavigate} />
                    ))}
                </div>
            )}
        </div>
    )
}
