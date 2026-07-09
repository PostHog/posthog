import { useActions, useValues } from 'kea'

import { IconArchive, IconArrowLeft, IconArrowRight, IconNotification } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import {
    NotificationGroup,
    sidePanelNotificationsLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PanelLayoutPanel } from '~/layout/panel-layout/PanelLayoutPanel'

import { NotificationGroupRow } from './NotificationGroupRow'
import { notificationsMenuLogic } from './notificationsMenuLogic'

export function NotificationsPanel(): JSX.Element {
    const { activeTab } = useValues(notificationsMenuLogic)
    const { setActiveTab } = useActions(notificationsMenuLogic)
    const {
        groups,
        archivedGroups,
        archivedLoaded,
        loadedUnreadCount,
        inAppUnreadCount,
        importantChangesLoading,
        hasMoreNotifications,
        hasMoreArchived,
        isLoadingMore,
        isLoadingMoreArchived,
        hasArchivableNotifications,
        archivingEnabled,
    } = useValues(sidePanelNotificationsLogic)
    const { markAllAsRead, loadMoreNotifications, loadMoreArchived, archiveAll } =
        useActions(sidePanelNotificationsLogic)
    const { closePanel } = useActions(panelLayoutLogic)

    const isArchivedTab = archivingEnabled && activeTab === 'archived'
    const filteredGroups = isArchivedTab
        ? archivedGroups
        : activeTab === 'unread'
          ? groups.filter((g: NotificationGroup) => g.has_unread)
          : groups

    const header = (
        <div className="flex items-center gap-2 flex-1 min-w-0">
            <div className="flex gap-1 pl-1">
                {/* TODO: make tab primitives */}
                <button
                    className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                        activeTab === 'all' ? 'bg-fill-highlight-100 text-primary' : 'text-secondary hover:text-primary'
                    }`}
                    onClick={() => setActiveTab('all')}
                >
                    All
                </button>
                <button
                    className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                        activeTab === 'unread'
                            ? 'bg-fill-highlight-100 text-primary'
                            : 'text-secondary hover:text-primary'
                    }`}
                    onClick={() => setActiveTab('unread')}
                >
                    Unread
                    {loadedUnreadCount > 0 && (
                        <span className="ml-1 text-[10px] text-danger font-bold">{loadedUnreadCount}</span>
                    )}
                </button>
                {/* Archived isn't a peer tab — it's reached from the ⋯ menu. Surface a static
                    marker while viewing it so the current context stays obvious. */}
                {isArchivedTab && (
                    <span className="px-2 py-1 text-xs font-medium rounded bg-fill-highlight-100 text-primary">
                        Archived
                    </span>
                )}
            </div>
            {/* Only surface "Mark all read" when unread items sit on not-yet-loaded pages — the ones
                already loaded get cleared by the 3s auto-mark-on-view as the user scrolls. */}
            {!isArchivedTab && hasMoreNotifications && inAppUnreadCount > loadedUnreadCount && (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => markAllAsRead()}
                    className="ml-auto"
                    data-attr="notifications-mark-all-read"
                >
                    Mark all read
                </LemonButton>
            )}
        </div>
    )

    // Archiving is flag-gated. With it off there's no ⋯ menu at all (the pre-clearable state);
    // with it on the ⋯ is always present — the entry point to the archived view and, on the
    // inbox, the home for the rare "Archive all" bulk action.
    const panelActions = !archivingEnabled
        ? undefined
        : isArchivedTab
          ? [
                {
                    'data-attr': 'notifications-view-inbox',
                    onClick: () => setActiveTab('all'),
                    children: (
                        <>
                            <IconArrowLeft />
                            Back to notifications
                        </>
                    ),
                },
            ]
          : [
                {
                    'data-attr': 'notifications-view-archived',
                    onClick: () => setActiveTab('archived'),
                    children: (
                        <>
                            <IconArrowRight />
                            View archived
                        </>
                    ),
                },
                hasArchivableNotifications
                    ? {
                          'data-attr': 'notifications-archive-all',
                          onClick: () => archiveAll(),
                          children: (
                              <>
                                  <IconArchive />
                                  Archive all
                              </>
                          ),
                      }
                    : null,
            ]

    return (
        <PanelLayoutPanel searchField={header} panelActionsNewSceneLayout={panelActions}>
            <ScrollableShadows
                direction="vertical"
                styledScrollbars
                className="flex-1 overflow-hidden"
                innerClassName="p-1"
            >
                {(isArchivedTab ? !archivedLoaded : importantChangesLoading && groups.length === 0) ? (
                    <div className="p-2">
                        <LemonSkeleton className="h-10 my-1" repeat={5} fade />
                    </div>
                ) : filteredGroups.length > 0 ? (
                    <>
                        <div className="flex flex-col gap-px">
                            {filteredGroups.map((group: NotificationGroup) => (
                                <NotificationGroupRow
                                    key={group.group_key}
                                    group={group}
                                    onNavigate={() => closePanel()}
                                    readOnly={isArchivedTab}
                                />
                            ))}
                        </div>
                        {isArchivedTab && hasMoreArchived && (
                            <div className="p-2">
                                <LemonButton
                                    type="secondary"
                                    fullWidth
                                    center
                                    size="small"
                                    loading={isLoadingMoreArchived}
                                    onClick={() => loadMoreArchived()}
                                >
                                    Load more
                                </LemonButton>
                            </div>
                        )}
                        {!isArchivedTab && hasMoreNotifications && activeTab === 'all' && (
                            <div className="p-2">
                                <LemonButton
                                    type="secondary"
                                    fullWidth
                                    center
                                    size="small"
                                    loading={isLoadingMore}
                                    onClick={() => loadMoreNotifications()}
                                >
                                    Load more
                                </LemonButton>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex flex-col items-center justify-center p-6 text-center">
                        <IconNotification className="size-8 text-muted mb-2" />
                        <span className="text-sm text-secondary">
                            {isArchivedTab
                                ? 'No archived notifications'
                                : activeTab === 'unread'
                                  ? "You're all caught up!"
                                  : 'No notifications yet'}
                        </span>
                    </div>
                )}
            </ScrollableShadows>
        </PanelLayoutPanel>
    )
}
