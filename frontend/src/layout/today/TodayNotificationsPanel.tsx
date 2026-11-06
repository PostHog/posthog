import { useActions, useValues } from 'kea'

import { IconArchive, IconArrowRight, IconEllipsis, IconNotification } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { NotificationGroupRow } from 'lib/components/NotificationsMenu/NotificationGroupRow'
import { NotificationTab, notificationsMenuLogic } from 'lib/components/NotificationsMenu/notificationsMenuLogic'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

export function TodayNotificationsPanel({ onNavigate }: { onNavigate: () => void }): JSX.Element {
    const { activeTab, isArchivedTab, visibleGroups, visibleGroupsLoading, showMarkAllRead, showLoadMore } =
        useValues(notificationsMenuLogic)
    const { setActiveTab } = useActions(notificationsMenuLogic)
    const { loadedUnreadCount, isLoadingMore, isLoadingMoreArchived, hasArchivableNotifications, archivingEnabled } =
        useValues(sidePanelNotificationsLogic)
    const { markAllAsRead, loadMoreNotifications, loadMoreArchived, archiveAll } =
        useActions(sidePanelNotificationsLogic)

    return (
        <>
            <div className="flex flex-none flex-wrap items-center gap-1 border-b border-border p-2">
                <ToggleGroup
                    value={[activeTab]}
                    onValueChange={(next) => {
                        const [picked] = next
                        if (picked) {
                            setActiveTab(picked as NotificationTab)
                        }
                    }}
                    aria-label="Notifications shown"
                >
                    <ToggleGroupItem value="all" size="sm">
                        All
                    </ToggleGroupItem>
                    <ToggleGroupItem
                        value="unread"
                        size="sm"
                        aria-label={loadedUnreadCount > 0 ? `Unread, ${loadedUnreadCount}` : undefined}
                    >
                        Unread
                        {loadedUnreadCount > 0 && <Badge variant="destructive">{loadedUnreadCount}</Badge>}
                    </ToggleGroupItem>
                    {isArchivedTab && (
                        <ToggleGroupItem value="archived" size="sm">
                            Archived
                        </ToggleGroupItem>
                    )}
                </ToggleGroup>
                <div className="ms-auto flex items-center gap-1">
                    {showMarkAllRead && (
                        <Button
                            variant="outline"
                            onClick={() => markAllAsRead()}
                            data-attr="notifications-mark-all-read"
                        >
                            Mark all read
                        </Button>
                    )}
                    {archivingEnabled && !isArchivedTab && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        size="icon"
                                        aria-label="More notification actions"
                                        tooltip="More notification actions"
                                    />
                                }
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem
                                    onClick={() => setActiveTab('archived')}
                                    data-attr="notifications-view-archived"
                                >
                                    <IconArrowRight />
                                    View archived
                                </DropdownMenuItem>
                                {hasArchivableNotifications && (
                                    <DropdownMenuItem
                                        onClick={() => archiveAll()}
                                        data-attr="notifications-archive-all"
                                    >
                                        <IconArchive />
                                        Archive all
                                    </DropdownMenuItem>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4 p-1">
                {visibleGroupsLoading ? (
                    <div className="flex flex-col gap-2 p-2">
                        {Array.from({ length: 5 }, (_, index) => (
                            <Skeleton key={index} className="h-10" />
                        ))}
                    </div>
                ) : visibleGroups.length > 0 ? (
                    <>
                        <div className="flex flex-col gap-px">
                            {visibleGroups.map((group) => (
                                <NotificationGroupRow
                                    key={group.group_key}
                                    group={group}
                                    onNavigate={onNavigate}
                                    readOnly={isArchivedTab}
                                />
                            ))}
                        </div>
                        {showLoadMore && (
                            <div className="p-2">
                                <Button
                                    variant="outline"
                                    className="w-full"
                                    loading={isArchivedTab ? isLoadingMoreArchived : isLoadingMore}
                                    onClick={() => (isArchivedTab ? loadMoreArchived() : loadMoreNotifications())}
                                >
                                    Load more
                                </Button>
                            </div>
                        )}
                    </>
                ) : (
                    <Empty>
                        <EmptyHeader>
                            <EmptyMedia variant="icon">
                                <IconNotification />
                            </EmptyMedia>
                            <EmptyTitle>
                                {isArchivedTab
                                    ? 'No archived notifications'
                                    : activeTab === 'unread'
                                      ? "You're all caught up!"
                                      : 'No notifications yet'}
                            </EmptyTitle>
                        </EmptyHeader>
                    </Empty>
                )}
            </div>
        </>
    )
}
