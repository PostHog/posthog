import { Combobox } from '@base-ui/react/combobox'
import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { formatConversationDate } from 'scenes/max/utils'
import { urls } from 'scenes/urls'

import { BrowserLikeMenuItems } from '~/layout/panel-layout/ProjectTree/menus/BrowserLikeMenuItems'
import { ConversationDetail, ConversationStatus } from '~/types'

function ConversationContextMenu({
    conversation,
    onClick,
    children,
}: {
    conversation: ConversationDetail
    onClick: () => void
    children: React.ReactNode
}): JSX.Element {
    const conversationUrl = combineUrl(urls.ai(conversation.id), { from: 'history' }).url

    return (
        <ContextMenu>
            <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
            <ContextMenuContent loop className="max-w-[250px]">
                <ContextMenuGroup>
                    <BrowserLikeMenuItems MenuItem={ContextMenuItem} href={conversationUrl} onClick={onClick} />
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

interface ConversationGroup {
    value: string
    items: ConversationDetail[]
}

const DATE_GROUP_ORDER = ['Today', 'Yesterday', 'Last 7 days', 'Last 30 days', 'Older']

function getDateGroupLabel(dateString: string | null): string {
    if (!dateString) {
        return 'Older'
    }

    const date = new Date(dateString)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    const lastWeek = new Date(today)
    lastWeek.setDate(lastWeek.getDate() - 7)
    const lastMonth = new Date(today)
    lastMonth.setDate(lastMonth.getDate() - 30)

    if (date >= today) {
        return 'Today'
    } else if (date >= yesterday) {
        return 'Yesterday'
    } else if (date >= lastWeek) {
        return 'Last 7 days'
    } else if (date >= lastMonth) {
        return 'Last 30 days'
    }
    return 'Older'
}

export function ConversationsMenu({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const [open, setOpen] = useState(false)
    const { conversationHistory, conversationHistoryLoading } = useValues(maxGlobalLogic)
    const { searchParams } = useValues(router)
    const currentConversationId = searchParams?.chat

    const [loadingStarted, setLoadingStarted] = useState(false)
    const [initialLoadComplete, setInitialLoadComplete] = useState(false)

    useEffect(() => {
        if (conversationHistoryLoading) {
            setLoadingStarted(true)
        } else if (loadingStarted && !initialLoadComplete) {
            setInitialLoadComplete(true)
        }
    }, [conversationHistoryLoading, loadingStarted, initialLoadComplete])

    const conversationGroups = useMemo(() => {
        const grouped: Record<string, ConversationDetail[]> = {}

        for (const conversation of conversationHistory) {
            const groupLabel = getDateGroupLabel(conversation.updated_at)
            if (!grouped[groupLabel]) {
                grouped[groupLabel] = []
            }
            grouped[groupLabel].push(conversation)
        }

        const groups: ConversationGroup[] = DATE_GROUP_ORDER.filter((label) => grouped[label]?.length > 0).map(
            (label) => ({
                value: label,
                items: grouped[label],
            })
        )

        return groups
    }, [conversationHistory])

    useAppShortcut({
        name: 'open-all-chats',
        keybind: [keyBinds.allChats],
        intent: 'Open all chats menu',
        interaction: 'function',
        callback: () => {
            setOpen(!open)
        },
    })

    return (
        <Combobox.Root
            open={open}
            onOpenChange={setOpen}
            items={conversationGroups}
            itemToStringValue={(item: ConversationDetail) => item.title || ''}
            defaultInputValue=""
            autoHighlight
        >
            <Combobox.Trigger
                render={
                    <ButtonPrimitive
                        iconOnly={isCollapsed}
                        tooltip={
                            <>
                                <span>All chats</span> <RenderKeybind keybind={[keyBinds.allChats]} />
                            </>
                        }
                        tooltipPlacement="right"
                        onClick={() => setOpen(!open)}
                        menuItem={!isCollapsed}
                        className="hidden lg:flex"
                    >
                        <IconEllipsis className="size-4 text-secondary" />
                        {!isCollapsed && (
                            <>
                                <span className="text-left">All chats</span>
                                <IconChevronRight className="size-3 text-secondary ml-auto" />
                            </>
                        )}
                    </ButtonPrimitive>
                }
            />
            <Combobox.Portal>
                <Combobox.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Combobox.Popup className="primitive-menu-content min-w-[300px] flex flex-col p-1 max-h-(--available-height)">
                        <Combobox.Input
                            placeholder="Search chats"
                            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
                            autoFocus
                        />
                        {!initialLoadComplete && (
                            <WrappingLoadingSkeleton fullWidth>
                                <ButtonPrimitive inert aria-hidden>
                                    Loading...
                                </ButtonPrimitive>
                            </WrappingLoadingSkeleton>
                        )}
                        {initialLoadComplete && (
                            <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                                <Combobox.List className="flex flex-col gap-1">
                                    {(group: ConversationGroup) => (
                                        <Combobox.Group
                                            key={group.value}
                                            items={group.items}
                                            className="flex flex-col gap-px"
                                        >
                                            <Combobox.GroupLabel className="flex px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10 justify-between">
                                                <span className="text-left">{group.value}</span>
                                                <span className="text-xs text-tertiary/80 shrink-0">Updated at</span>
                                            </Combobox.GroupLabel>
                                            <Combobox.Collection>
                                                {(conversation: ConversationDetail) => (
                                                    <ConversationContextMenu
                                                        key={conversation.id}
                                                        conversation={conversation}
                                                        onClick={() => setOpen(false)}
                                                    >
                                                        <Combobox.Item
                                                            value={conversation}
                                                            render={
                                                                <Link
                                                                    to={
                                                                        combineUrl(urls.ai(conversation.id), {
                                                                            from: 'history',
                                                                        }).url
                                                                    }
                                                                    buttonProps={{
                                                                        active:
                                                                            conversation.id === currentConversationId,
                                                                        menuItem: true,
                                                                    }}
                                                                    tooltip={conversation.title}
                                                                    tooltipPlacement="right"
                                                                    onClick={() => setOpen(false)}
                                                                >
                                                                    <span className="flex-1 line-clamp-1">
                                                                        {conversation.title}
                                                                    </span>
                                                                    {conversation.status ===
                                                                        ConversationStatus.InProgress && (
                                                                        <Spinner className="h-3 w-3" />
                                                                    )}
                                                                    <span className="text-xs text-tertiary/80 shrink-0">
                                                                        {formatConversationDate(
                                                                            conversation.updated_at
                                                                        )}
                                                                    </span>
                                                                </Link>
                                                            }
                                                        />
                                                    </ConversationContextMenu>
                                                )}
                                            </Combobox.Collection>
                                        </Combobox.Group>
                                    )}
                                </Combobox.List>
                                <Combobox.Empty className="px-2 py-4 text-center text-sm text-muted empty:hidden">
                                    No chats found.
                                </Combobox.Empty>
                            </ScrollableShadows>
                        )}
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}
