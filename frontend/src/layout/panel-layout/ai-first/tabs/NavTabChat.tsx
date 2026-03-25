import { Combobox } from '@base-ui/react/combobox'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { cn } from 'lib/utils/css-classes'
import { AiChatListItem } from 'scenes/max/components/List/AiChatListItem'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { Conversation } from '~/types'

const DATE_GROUP_ORDER = ['Today', 'Yesterday', 'Last 7 days', 'Last 30 days', 'Older'] as const

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

interface ConversationGroup {
    value: string
    items: Conversation[]
}

export function NavTabChat({
    inPanel = false,
    onItemClick,
}: {
    inPanel?: boolean
    onItemClick?: () => void
}): JSX.Element {
    const { conversationHistory, conversationHistoryLoading, currentConversationId } = useValues(maxGlobalLogic)
    const [inputValue, setInputValue] = useState('')

    const conversationGroups = useMemo(() => {
        const grouped: Record<string, Conversation[]> = {}
        for (const conversation of conversationHistory) {
            const label = getDateGroupLabel(conversation.updated_at)
            if (!grouped[label]) {
                grouped[label] = []
            }
            grouped[label].push(conversation)
        }

        return DATE_GROUP_ORDER.filter((label) => grouped[label]?.length > 0).map(
            (label): ConversationGroup => ({ value: label, items: grouped[label] })
        )
    }, [conversationHistory])

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <Combobox.Root
                items={conversationGroups}
                itemToStringValue={(item: Conversation) => item?.title ?? ''}
                open
                autoHighlight
                inline
                inputValue={inputValue}
                onInputValueChange={setInputValue}
            >
                <div className="flex flex-col h-full min-h-0">
                    <div className={cn('flex items-center gap-1 p-2 shrink-0', inPanel && 'p-1')}>
                        <label
                            htmlFor="nav-search-chats"
                            className={cn(
                                'input-like flex items-center flex-1 px-1 gap-1 group h-[30px]',
                                inPanel && 'bg-fill-input'
                            )}
                        >
                            <IconSearch className="size-4 text-tertiary group-focus-within:text-primary w-4 shrink-0" />
                            <Combobox.Input
                                id="nav-search-chats"
                                placeholder="Chat history"
                                aria-label="Chat history"
                                className="w-full text-sm bg-transparent border-none focus:outline-none focus:ring-0 transition-[width] duration-100 h-[30px]"
                                autoFocus={inPanel}
                            />
                            {inputValue && (
                                <ButtonPrimitive
                                    iconOnly
                                    onClick={() => setInputValue('')}
                                    className="shrink-0 -mr-1"
                                    tooltip="Clear search"
                                >
                                    <IconX className="size-3 text-tertiary" />
                                </ButtonPrimitive>
                            )}
                        </label>
                        <Link
                            to={urls.ai()}
                            buttonProps={{ iconOnly: true, variant: 'outline', className: 'text-ai' }}
                            tooltip="New chat"
                        >
                            <IconPlusSmall className="size-4" />
                        </Link>
                    </div>

                    <ScrollableShadows
                        direction="vertical"
                        className="flex flex-col flex-1 min-h-0 overflow-hidden"
                        innerClassName="flex flex-col px-1 pb-4 -mx-1 scroll-pt-8 focus-visible:outline-accent -outline-offset-2"
                        styledScrollbars
                    >
                        {conversationHistoryLoading && conversationHistory.length === 0 ? (
                            <div className="flex flex-col gap-1 px-1">
                                <LemonSkeleton className="h-8" />
                                <LemonSkeleton className="h-8 opacity-60" />
                                <LemonSkeleton className="h-8 opacity-30" />
                            </div>
                        ) : (
                            <>
                                <Combobox.List className="flex flex-col">
                                    {(group: ConversationGroup) => (
                                        <Collapsible
                                            key={group.value}
                                            defaultOpen={group.value === 'Today' || conversationGroups.length === 1}
                                        >
                                            <Combobox.Group items={group.items}>
                                                <Combobox.GroupLabel
                                                    render={
                                                        <Collapsible.Trigger className="sticky top-0 bg-surface-tertiary z-4 pl-3" />
                                                    }
                                                >
                                                    {group.value}
                                                </Combobox.GroupLabel>
                                                <Collapsible.Panel className="p-1 pl-3">
                                                    <Combobox.Collection>
                                                        {(conversation: Conversation) => (
                                                            <AiChatListItem.Root>
                                                                <AiChatListItem.Group>
                                                                    <Combobox.Item
                                                                        key={conversation.id}
                                                                        value={conversation}
                                                                        render={(props) => (
                                                                            <Tooltip
                                                                                title={
                                                                                    conversation.title ||
                                                                                    'view conversation'
                                                                                }
                                                                                placement="right"
                                                                            >
                                                                                <Link
                                                                                    {...props}
                                                                                    to={AiChatListItem.getHref(
                                                                                        conversation.id
                                                                                    )}
                                                                                    buttonProps={{
                                                                                        active:
                                                                                            conversation.id ===
                                                                                            currentConversationId,
                                                                                        fullWidth: true,
                                                                                        className: 'pr-0',
                                                                                        menuItem: true,
                                                                                    }}
                                                                                    extraContextMenuItems={
                                                                                        <AiChatListItem.ContextMenuAction
                                                                                            conversationId={
                                                                                                conversation.id
                                                                                            }
                                                                                        />
                                                                                    }
                                                                                    onClick={(e) => {
                                                                                        e.preventDefault()
                                                                                        router.actions.push(
                                                                                            AiChatListItem.getHref(
                                                                                                conversation.id
                                                                                            )
                                                                                        )
                                                                                        onItemClick?.()
                                                                                    }}
                                                                                >
                                                                                    <AiChatListItem.Content
                                                                                        title={conversation.title}
                                                                                        status={conversation.status}
                                                                                        updatedAt={
                                                                                            conversation.updated_at
                                                                                        }
                                                                                    />
                                                                                </Link>
                                                                            </Tooltip>
                                                                        )}
                                                                    />
                                                                    <AiChatListItem.Trigger />
                                                                </AiChatListItem.Group>
                                                                <AiChatListItem.Actions
                                                                    conversationId={conversation.id}
                                                                />
                                                            </AiChatListItem.Root>
                                                        )}
                                                    </Combobox.Collection>
                                                </Collapsible.Panel>
                                            </Combobox.Group>
                                        </Collapsible>
                                    )}
                                </Combobox.List>
                                <div className="p-2 empty:hidden">
                                    <Combobox.Empty className="empty:hidden">
                                        <div className="flex flex-col items-center justify-center text-center py-8 text-muted border border-dashed rounded-md">
                                            <p className="text-xs mb-0">No chats found</p>
                                        </div>
                                    </Combobox.Empty>
                                </div>
                            </>
                        )}
                    </ScrollableShadows>
                </div>
            </Combobox.Root>
        </div>
    )
}
