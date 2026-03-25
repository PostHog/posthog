import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import { memo, useRef } from 'react'

import { IconPlusSmall, IconSearch, IconSidebarClose } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { ConversationDetail } from '~/types'

import { maxLogic } from '../maxLogic'
import { CHAT_HISTORY_COLLAPSE_THRESHOLD, maxPanelSizingLogic } from '../maxPanelSizingLogic'
import { AiChatListItem } from './List/AiChatListItem'

interface ChatHistoryPanelProps {
    tabId: string
}

export const ChatHistoryPanel = memo(function ChatHistoryPanel({ tabId }: ChatHistoryPanelProps): JSX.Element {
    const chatHistoryPanelRef = useRef<HTMLDivElement>(null)
    const { startNewConversation, openConversation } = useActions(maxLogic({ tabId }))
    const { conversationHistory, conversationHistoryLoading, conversationId } = useValues(maxLogic({ tabId }))

    const resizerProps: ResizerLogicProps = {
        containerRef: chatHistoryPanelRef,
        logicKey: 'max-chat-history-panel',
        persistent: true,
        closeThreshold: CHAT_HISTORY_COLLAPSE_THRESHOLD,
        placement: 'right',
    }

    const { chatHistoryPanelWidth, isChatHistoryPanelCollapsed, chatHistoryPanelWillCollapse } = useValues(
        maxPanelSizingLogic({
            chatHistoryPanelRef,
            chatHistoryPanelResizerProps: resizerProps,
        })
    )

    const { toggleChatHistoryPanelCollapsed, setChatHistoryPanelCollapsed } = useActions(
        maxPanelSizingLogic({
            chatHistoryPanelRef,
            chatHistoryPanelResizerProps: resizerProps,
        })
    )

    return (
        <div
            className={cn(
                'relative flex flex-col bg-primary border-r border-primary transition-opacity duration-100 max-w-[var(--chat-history-panel-width)] h-full overflow-hidden',
                isChatHistoryPanelCollapsed ? 'w-12' : `w-[var(--chat-history-panel-width)]`,
                chatHistoryPanelWillCollapse && 'opacity-50'
            )}
            style={
                {
                    '--chat-history-panel-width': `${chatHistoryPanelWidth}px`,
                } as React.CSSProperties & { '--chat-history-panel-width': string }
            }
            ref={chatHistoryPanelRef}
        >
            <Autocomplete.Root
                items={conversationHistory}
                filter={(item, query) => (item?.title || '').toLowerCase().includes(query.toLowerCase())}
                itemToStringValue={(item: ConversationDetail) => item?.title ?? ''}
                inline
                defaultOpen
                autoHighlight={true}
            >
                <div className="flex flex-col h-full min-h-0">
                    <div className="flex items-center gap-1 p-2 shrink-0">
                        <ButtonPrimitive
                            onClick={toggleChatHistoryPanelCollapsed}
                            data-attr="max-toggle-chat-history"
                            tooltip={isChatHistoryPanelCollapsed ? 'Expand history' : 'Collapse history'}
                            className="h-[32px]"
                            iconOnly
                        >
                            <IconSidebarClose
                                className={cn('size-4 text-tertiary', !isChatHistoryPanelCollapsed && 'rotate-180')}
                            />
                        </ButtonPrimitive>
                        {!isChatHistoryPanelCollapsed && (
                            <>
                                <label
                                    htmlFor="search-chats"
                                    className="input-like flex items-center flex-1 px-1 gap-1 group h-[30px]"
                                >
                                    <IconSearch className="size-3 text-tertiary group-focus-within:text-primary w-4 shrink-0" />
                                    <Autocomplete.Input
                                        id="search-chats"
                                        data-attr="max-search-chat-history"
                                        placeholder="Chat history"
                                        aria-label="Chat history"
                                        className={cn(
                                            'w-full text-sm bg-transparent border-none focus:outline-none focus:ring-0 transition-[width] duration-100 h-[30px]'
                                        )}
                                    />
                                </label>
                                <ButtonPrimitive
                                    variant="outline"
                                    iconOnly
                                    onClick={() => startNewConversation()}
                                    data-attr="max-new-chat"
                                    tooltip="New chat"
                                >
                                    <IconPlusSmall />
                                </ButtonPrimitive>
                            </>
                        )}
                    </div>

                    {!isChatHistoryPanelCollapsed && (
                        <ScrollableShadows
                            direction="vertical"
                            className="flex flex-col flex-1 min-h-0 overflow-hidden"
                            innerClassName="flex flex-col px-2 pt-2 pb-4"
                            styledScrollbars
                        >
                            {conversationHistoryLoading && conversationHistory.length === 0 ? (
                                <div className="flex flex-col gap-1">
                                    <LemonSkeleton className="h-8" />
                                    <LemonSkeleton className="h-8 opacity-60" />
                                    <LemonSkeleton className="h-8 opacity-30" />
                                </div>
                            ) : (
                                <>
                                    <Autocomplete.List className="flex flex-col gap-1 -mx-1">
                                        <Autocomplete.Group items={conversationHistory}>
                                            <Autocomplete.Collection>
                                                {(conversation: ConversationDetail) => (
                                                    <AiChatListItem.Root>
                                                        <AiChatListItem.Group>
                                                            <Autocomplete.Item
                                                                key={conversation.id}
                                                                value={conversation}
                                                                onClick={(e) => {
                                                                    e.preventDefault()
                                                                    openConversation(conversation.id)
                                                                }}
                                                                render={
                                                                    <Link
                                                                        to={AiChatListItem.getHref(conversation.id)}
                                                                        buttonProps={{
                                                                            active: conversation.id === conversationId,
                                                                            fullWidth: true,
                                                                            className: 'pr-0',
                                                                        }}
                                                                        tooltip={
                                                                            conversation.title || 'view conversation'
                                                                        }
                                                                        tooltipPlacement="right"
                                                                        extraContextMenuItems={
                                                                            <AiChatListItem.ContextMenuAction
                                                                                conversationId={conversation.id}
                                                                            />
                                                                        }
                                                                    >
                                                                        <AiChatListItem.Content
                                                                            showIcon
                                                                            title={conversation.title}
                                                                            status={conversation.status}
                                                                            updatedAt={conversation.updated_at}
                                                                        />
                                                                    </Link>
                                                                }
                                                            />
                                                            <AiChatListItem.Trigger />
                                                        </AiChatListItem.Group>
                                                        <AiChatListItem.Actions conversationId={conversation.id} />
                                                    </AiChatListItem.Root>
                                                )}
                                            </Autocomplete.Collection>
                                        </Autocomplete.Group>
                                    </Autocomplete.List>
                                    <Autocomplete.Empty className="flex flex-col items-center justify-center text-center py-8 text-muted empty:hidden">
                                        <p className="text-sm mb-0">No chats found</p>
                                    </Autocomplete.Empty>
                                </>
                            )}
                        </ScrollableShadows>
                    )}
                </div>
            </Autocomplete.Root>

            <Resizer
                containerRef={chatHistoryPanelRef}
                logicKey="max-chat-history-panel"
                placement="right"
                persistent
                closeThreshold={CHAT_HISTORY_COLLAPSE_THRESHOLD}
                onToggleClosed={(closed) => setChatHistoryPanelCollapsed(closed)}
            />
        </div>
    )
})
