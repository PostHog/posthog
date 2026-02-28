import { Combobox } from '@base-ui/react/combobox'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconChevronRight, IconClock, IconMessage } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

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

export function RecentsMenu(): JSX.Element {
    const { recentItems, recentItemsLoading } = useValues(recentItemsMenuLogic)
    const { loadRecentItems } = useActions(recentItemsMenuLogic)
    const { conversationHistory, conversationHistoryLoading } = useValues(maxGlobalLogic)
    const { loadConversationHistory } = useActions(maxGlobalLogic)
    const [open, setOpen] = useState(false)

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

    const isLoading = recentItemsLoading || conversationHistoryLoading

    return (
        <Combobox.Root
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (nextOpen) {
                    loadRecentItems({})
                    loadConversationHistory({})
                }
            }}
            items={groups}
            itemToStringValue={(item: RecentItem) => item.label}
            defaultInputValue=""
            autoHighlight
        >
            <Combobox.Trigger
                render={
                    <ButtonPrimitive menuItem>
                        <IconClock className="size-4 text-secondary" />
                        <span className="flex-1 text-left">Recent</span>
                        <IconChevronRight className="size-3 text-secondary" />
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
                    <Combobox.Popup className="primitive-menu-content min-w-[300px] flex flex-col p-1 h-(--available-height)">
                        <Combobox.Input
                            placeholder="Search recent"
                            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
                            autoFocus
                        />
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            {isLoading ? (
                                <div className="px-2 py-4 text-center text-sm text-muted">Loading...</div>
                            ) : (
                                <Combobox.List className="flex flex-col gap-1">
                                    {(group: RecentGroup) => (
                                        <Combobox.Group
                                            key={group.value}
                                            items={group.items}
                                            className="flex flex-col gap-px"
                                        >
                                            <Combobox.GroupLabel className="px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10">
                                                {group.value}
                                            </Combobox.GroupLabel>
                                            <Combobox.Collection>
                                                {(item: RecentItem) => (
                                                    <Combobox.Item
                                                        key={item.id}
                                                        value={item}
                                                        className={menuItemStyles}
                                                        onClick={() => {
                                                            router.actions.push(item.href)
                                                            setOpen(false)
                                                        }}
                                                        render={
                                                            <ButtonPrimitive menuItem>
                                                                {item.icon}
                                                                <span className="flex-1 truncate">{item.label}</span>
                                                            </ButtonPrimitive>
                                                        }
                                                    />
                                                )}
                                            </Combobox.Collection>
                                        </Combobox.Group>
                                    )}
                                </Combobox.List>
                            )}
                            <Combobox.Empty className="px-2 py-4 text-center text-sm text-muted empty:hidden">
                                No recent items found.
                            </Combobox.Empty>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}
