import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconClock, IconMessage } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { MenuSearchInput } from '~/layout/panel-layout/ai-first/MenuSearchInput'
import { MenuTrigger } from '~/layout/panel-layout/ai-first/MenuTrigger'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { recentItemsMenuLogic } from '~/layout/panel-layout/ProjectTree/menus/recentItemsMenuLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { maxGlobalLogic } from '../../../scenes/max/maxGlobalLogic'

const menuItemStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover outline-none data-[highlighted]:bg-fill-button-tertiary-hover'

interface RecentItem {
    id: string
    label: string
    icon: React.ReactNode
    href: string
}

interface RecentGroup {
    value: string
    items: RecentItem[]
}

const getItemName = (item: FileSystemEntry): string => {
    const pathSplit = splitPath(item.path)
    const lastPart = pathSplit.pop()
    return unescapePath(lastPart ?? item.path)
}

export function RecentsMenu({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { recentItems, recentItemsLoading } = useValues(recentItemsMenuLogic)
    const { loadRecentItems } = useActions(recentItemsMenuLogic)
    const { conversationHistory, conversationHistoryLoading } = useValues(maxGlobalLogic)
    const { loadConversationHistory } = useActions(maxGlobalLogic)
    const [searchTerm, setSearchTerm] = useState('')

    const groups = useMemo((): RecentGroup[] => {
        const conversationItems: RecentItem[] = (conversationHistory ?? []).slice(0, 10).map((c) => ({
            id: `conv-${c.id}`,
            label: c.title || 'Untitled conversation',
            icon: <IconMessage className="size-4 text-secondary" />,
            href: urls.ai(c.id),
        }))

        const fileItems: RecentItem[] = (recentItems ?? []).map((item: FileSystemEntry) => ({
            id: `file-${item.id}`,
            label: getItemName(item),
            icon: iconForType(item.type as FileSystemIconType),
            href: item.href || '#',
        }))

        const result: RecentGroup[] = []
        if (conversationItems.length > 0) {
            result.push({ value: 'Conversations', items: conversationItems })
        }
        if (fileItems.length > 0) {
            result.push({ value: 'Items', items: fileItems })
        }
        return result
    }, [conversationHistory, recentItems])

    const filteredGroups = useMemo(() => {
        if (!searchTerm) {
            return groups
        }
        const term = searchTerm.toLowerCase()
        return groups
            .map((group) => ({
                ...group,
                items: group.items.filter((item) => item.label.toLowerCase().includes(term)),
            }))
            .filter((group) => group.items.length > 0)
    }, [groups, searchTerm])

    const isLoading = recentItemsLoading || conversationHistoryLoading

    return (
        <Menu.Root
            onOpenChange={(open) => {
                if (open) {
                    loadRecentItems({})
                    loadConversationHistory({})
                } else {
                    setSearchTerm('')
                }
            }}
        >
            <MenuTrigger label="Recents" icon={<IconClock />} isCollapsed={isCollapsed} />
            <Menu.Portal>
                <Menu.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Menu.Popup className="primitive-menu-content min-w-[300px] flex flex-col p-1 h-(--available-height)">
                        <MenuSearchInput
                            placeholder="Search recents"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            {isLoading ? (
                                <div className="px-2 py-4 text-center text-sm text-muted">Loading...</div>
                            ) : (
                                <div className="flex flex-col gap-1">
                                    {filteredGroups.map((group) => (
                                        <Menu.Group key={group.value} className="flex flex-col gap-px">
                                            <Menu.GroupLabel className="px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10">
                                                {group.value}
                                            </Menu.GroupLabel>
                                            {group.items.map((item) => (
                                                <Menu.Item
                                                    key={item.id}
                                                    className={menuItemStyles}
                                                    label={item.label}
                                                    onClick={() => router.actions.push(item.href)}
                                                    render={
                                                        <ButtonPrimitive menuItem>
                                                            {item.icon}
                                                            <span className="flex-1 truncate">{item.label}</span>
                                                        </ButtonPrimitive>
                                                    }
                                                />
                                            ))}
                                        </Menu.Group>
                                    ))}
                                    {filteredGroups.length === 0 && (
                                        <div className="px-2 py-4 text-center text-sm text-muted">
                                            No recent items found.
                                        </div>
                                    )}
                                </div>
                            )}
                        </ScrollableShadows>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
