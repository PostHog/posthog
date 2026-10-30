import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
    Spinner,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    anchoredToast,
    cn,
} from '@posthog/quill'

import { todayAiChatLogic } from './todayAiChatLogic'
import { todayPanelChatSessionLogic } from './todayPanelChatSessionLogic'
import { TodaySessionIcon } from './TodaySessionIcon'

interface TodayAiChatTitleMenuProps {
    showChevron?: boolean
}

export function TodayAiChatTitleMenu({ showChevron = true }: TodayAiChatTitleMenuProps): JSX.Element {
    const { chatTitle, recentGroups, recentLoading, activeItemId, unreadSessionIds } = useValues(todayAiChatLogic)
    const { openRecentItem } = useActions(todayAiChatLogic)
    const { previousChatsHintQueued } = useValues(todayPanelChatSessionLogic)
    const { previousChatsHintShown } = useActions(todayPanelChatSessionLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    // The hint can be queued while the panel is closed, so it shows when this menu mounts.
    useEffect(() => {
        if (previousChatsHintQueued && triggerRef.current) {
            anchoredToast({
                description: 'Previous chats can be found here',
                anchor: triggerRef.current,
                side: 'bottom',
            })
            previousChatsHintShown()
        }
    }, [previousChatsHintQueued, previousChatsHintShown])

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    ref={triggerRef}
                                    className="min-w-0 shrink gap-1.5 px-1.5 font-semibold"
                                    data-attr="today-ai-chat-recents"
                                >
                                    <span className="min-w-0 truncate">{chatTitle}</span>
                                    {showChevron && (
                                        <IconChevronDown className="size-3 shrink-0 text-muted-foreground" />
                                    )}
                                </Button>
                            }
                        />
                    }
                />
                <TooltipContent side="bottom" align="start" className="max-w-80">
                    {chatTitle}
                </TooltipContent>
            </Tooltip>
            <DropdownMenuContent className="w-72">
                {recentGroups.length === 0 ? (
                    recentLoading ? (
                        <div className="flex items-center gap-2 px-2 py-1.5 text-muted-foreground">
                            <Spinner />
                            Loading chats
                        </div>
                    ) : (
                        <div className="px-2 py-1.5 text-muted-foreground">No chats yet</div>
                    )
                ) : (
                    recentGroups.map((group) => (
                        <DropdownMenuGroup key={group.key}>
                            <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
                            {group.items.map((item) => (
                                <DropdownMenuItem
                                    key={item.id}
                                    onClick={() => openRecentItem(item)}
                                    data-attr="today-ai-chat-recent-item"
                                    className={cn(item.id === activeItemId && 'bg-[var(--fill-selected)]')}
                                >
                                    <span className="flex size-4 shrink-0 items-center justify-center">
                                        <TodaySessionIcon item={item} unread={unreadSessionIds.has(item.id)} />
                                    </span>
                                    <span className="min-w-0 truncate">{item.title || 'Untitled chat'}</span>
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                    ))
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
