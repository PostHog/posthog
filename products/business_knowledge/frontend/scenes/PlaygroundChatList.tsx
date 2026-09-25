import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'

export function PlaygroundChatList(): JSX.Element {
    const { chats, chatsLoading, chatId, deletingChatId } = useValues(businessKnowledgePlaygroundLogic)
    const { newChat, deleteChat } = useActions(businessKnowledgePlaygroundLogic)

    return (
        <aside
            className="flex max-h-40 min-h-0 min-w-0 shrink-0 flex-col gap-1 overflow-y-auto @min-[32.5625rem]:max-h-none @min-[32.5625rem]:w-56 @min-[32.5625rem]:border-r @min-[32.5625rem]:pr-2"
            // pinned: autocapture / Playwright key. Do not rename.
            data-attr="business-knowledge-playground-chat-list"
        >
            <LemonButton
                type="secondary"
                icon={<IconPlus />}
                onClick={() => newChat()}
                // pinned: autocapture / Playwright key. Do not rename.
                data-attr="business-knowledge-playground-new-chat"
            >
                New chat
            </LemonButton>
            {chatsLoading && chats.length === 0 ? (
                <div className="flex flex-col gap-1">
                    <LemonSkeleton className="h-8" />
                    <LemonSkeleton className="h-8 opacity-60" />
                    <LemonSkeleton className="h-8 opacity-30" />
                </div>
            ) : null}
            {chats.map((chat) => (
                <LemonButton
                    key={chat.id}
                    to={urls.businessKnowledgePlayground(chat.id)}
                    active={chat.id === chatId}
                    fullWidth
                    truncate
                    {...(chat.id === chatId
                        ? {
                              sideAction: {
                                  icon: <IconTrash />,
                                  status: 'danger' as const,
                                  disabled: deletingChatId === chat.id,
                                  loading: deletingChatId === chat.id,
                                  onClick: () => deleteChat(chat.id),
                                  'aria-label': 'Delete chat',
                              },
                          }
                        : {})}
                >
                    {chat.title || 'New chat'}
                </LemonButton>
            ))}
        </aside>
    )
}
