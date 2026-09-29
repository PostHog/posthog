import { useActions, useValues } from 'kea'

import { IconMessage, IconPlusSmall, IconSearch, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { urls } from 'scenes/urls'

import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'
import { formatChatAge } from './playgroundDisplay'

export function PlaygroundChatList(): JSX.Element {
    const {
        chats,
        chatsLoading,
        chatGroups,
        chatSearch,
        chatId,
        chatHasOpenTurn,
        deletingChatId,
        nextChatsOffset,
        loadingMoreChats,
        moreChatsError,
    } = useValues(businessKnowledgePlaygroundLogic)
    const { newChat, deleteChat, setChatSearch, loadMoreChats } = useActions(businessKnowledgePlaygroundLogic)

    const confirmDelete = (id: string): void => {
        LemonDialog.open({
            title: 'Delete chat?',
            description: 'The chat will be removed from your history. An answer in progress keeps running.',
            primaryButton: { children: 'Delete', status: 'danger', onClick: () => deleteChat(id) },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <aside
            className="flex max-h-48 min-h-0 min-w-0 shrink-0 flex-col border-b @min-[32.5625rem]:max-h-none @min-[32.5625rem]:w-60 @min-[32.5625rem]:border-r @min-[32.5625rem]:border-b-0"
            // pinned: autocapture / Playwright key. Do not rename.
            data-attr="business-knowledge-playground-chat-list"
        >
            <div className="flex shrink-0 items-center gap-1 p-1">
                <LemonInput
                    type="search"
                    size="small"
                    className="min-h-[30px] min-w-0 flex-1"
                    placeholder="Filter loaded chats"
                    aria-label="Filter loaded chats"
                    value={chatSearch}
                    onChange={setChatSearch}
                    fullWidth
                    prefix={<IconSearch className="size-4" />}
                />
                <ButtonPrimitive
                    iconOnly
                    variant="outline"
                    className="text-ai"
                    tooltip="New chat"
                    onClick={() => newChat()}
                    // pinned: autocapture / Playwright key. Do not rename.
                    data-attr="business-knowledge-playground-new-chat"
                >
                    <IconPlusSmall className="size-4" />
                </ButtonPrimitive>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-1 pb-4">
                {chatsLoading && chats.length === 0 ? (
                    <div className="flex flex-col gap-1 px-1">
                        <LemonSkeleton className="h-8" />
                        <LemonSkeleton className="h-8 opacity-60" />
                        <LemonSkeleton className="h-8 opacity-30" />
                    </div>
                ) : chatGroups.length === 0 ? (
                    <div className="m-1 rounded-md border border-dashed py-8 text-center text-muted">
                        <p className="mb-0 text-xs">{chatSearch ? 'No chats found' : 'No chats yet'}</p>
                    </div>
                ) : (
                    chatGroups.map((group) => (
                        <Collapsible
                            key={`${group.label}-${!!chatSearch}`}
                            defaultOpen={
                                !!chatSearch ||
                                group.label === 'Today' ||
                                chatGroups.length === 1 ||
                                group.chats.some((chat) => chat.id === chatId)
                            }
                        >
                            <Collapsible.Trigger className="pl-2">{group.label}</Collapsible.Trigger>
                            <Collapsible.Panel className="p-1 pl-2">
                                {group.chats.map((chat) => (
                                    <LinkListItem.Root key={chat.id}>
                                        <LinkListItem.Group>
                                            <Link
                                                to={urls.businessKnowledgePlayground(chat.id)}
                                                buttonProps={{
                                                    active: chat.id === chatId,
                                                    fullWidth: true,
                                                    menuItem: true,
                                                    className: 'pr-0',
                                                }}
                                                tooltip={chat.title || 'New chat'}
                                                tooltipPlacement="right"
                                                // pinned: autocapture / Playwright key. Do not rename.
                                                data-attr="business-knowledge-playground-open-chat"
                                            >
                                                <LinkListItem.Content
                                                    icon={<IconMessage />}
                                                    title={chat.title || 'New chat'}
                                                    isLoading={
                                                        (chat.id === chatId ? chatHasOpenTurn : chat.has_open_turn) ||
                                                        deletingChatId === chat.id
                                                    }
                                                    meta={formatChatAge(chat.updated_at)}
                                                />
                                            </Link>
                                            <LinkListItem.Trigger />
                                        </LinkListItem.Group>
                                        <LinkListItem.Actions>
                                            <DropdownMenuGroup>
                                                <DropdownMenuItem asChild>
                                                    <ButtonPrimitive
                                                        menuItem
                                                        disabled={deletingChatId !== null}
                                                        onClick={() => confirmDelete(chat.id)}
                                                        // pinned: autocapture / Playwright key. Do not rename.
                                                        data-attr="business-knowledge-playground-delete-chat"
                                                    >
                                                        <IconTrash className="size-4 text-danger" />
                                                        <span className="text-danger">Delete chat</span>
                                                    </ButtonPrimitive>
                                                </DropdownMenuItem>
                                            </DropdownMenuGroup>
                                        </LinkListItem.Actions>
                                    </LinkListItem.Root>
                                ))}
                            </Collapsible.Panel>
                        </Collapsible>
                    ))
                )}
                {moreChatsError && (
                    <p role="alert" className="px-2 text-xs text-danger">
                        {moreChatsError}
                    </p>
                )}
                {nextChatsOffset !== null && (
                    <LemonButton
                        size="small"
                        center
                        loading={loadingMoreChats}
                        disabledReason={chatsLoading ? 'Wait for chats to load' : undefined}
                        onClick={loadMoreChats}
                    >
                        Load more chats
                    </LemonButton>
                )}
            </div>
        </aside>
    )
}
