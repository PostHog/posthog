import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { memo, useRef } from 'react'

import { IconEllipsis, IconPlusSmall, IconSearch, IconShare, IconSidebarClose } from '@posthog/icons'
import { LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { ConversationDetail, ConversationStatus } from '~/types'

import { maxLogic } from '../maxLogic'
import { CHAT_HISTORY_COLLAPSE_THRESHOLD, maxPanelSizingLogic } from '../maxPanelSizingLogic'
import { formatConversationDate } from '../utils'

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
                                                    <DropdownMenu>
                                                        <ButtonGroupPrimitive fullWidth className="group">
                                                            <Autocomplete.Item
                                                                key={conversation.id}
                                                                value={conversation}
                                                                onClick={(e) => {
                                                                    e.preventDefault()
                                                                    openConversation(conversation.id)
                                                                }}
                                                                render={
                                                                    <Link
                                                                        to={
                                                                            combineUrl(urls.ai(conversation.id), {
                                                                                from: 'history',
                                                                            }).url
                                                                        }
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
                                                                            <ContextMenuItem asChild>
                                                                                <ButtonPrimitive
                                                                                    menuItem
                                                                                    onClick={() => {
                                                                                        copyToClipboard(
                                                                                            urls.absolute(
                                                                                                urls.currentProject(
                                                                                                    urls.ai(
                                                                                                        conversation.id
                                                                                                    )
                                                                                                )
                                                                                            ),
                                                                                            'conversation sharing link'
                                                                                        )
                                                                                    }}
                                                                                >
                                                                                    <IconShare className="size-4 text-tertiary" />
                                                                                    Copy link to chat
                                                                                </ButtonPrimitive>
                                                                            </ContextMenuItem>
                                                                        }
                                                                    >
                                                                        <span className="flex-1 line-clamp-1 text-primary">
                                                                            {conversation.title}
                                                                        </span>
                                                                        {conversation.status ===
                                                                            ConversationStatus.InProgress && (
                                                                            <Spinner className="h-3 w-3" />
                                                                        )}
                                                                        <span className="opacity-30 text-xs pr-1.5 group-hover:opacity-0 group-has-[[data-state=open]]:opacity-0 transition-opacity duration-100">
                                                                            {formatConversationDate(
                                                                                conversation.updated_at
                                                                            )}
                                                                        </span>
                                                                    </Link>
                                                                }
                                                            />
                                                            <DropdownMenuTrigger asChild>
                                                                <ButtonPrimitive
                                                                    iconOnly
                                                                    className="
                                                                        absolute right-0
                                                                        translate-x-full opacity-0
                                                                        group-hover:translate-x-0 group-hover:opacity-100
                                                                        data-[state=open]:translate-x-0
                                                                        data-[state=open]:opacity-100
                                                                        transition-[opacity] duration-100 ease-initial
                                                                    "
                                                                >
                                                                    <IconEllipsis className="text-tertiary size-3 group-hover:text-primary z-10" />
                                                                </ButtonPrimitive>
                                                            </DropdownMenuTrigger>
                                                        </ButtonGroupPrimitive>
                                                        <DropdownMenuContent>
                                                            <DropdownMenuGroup>
                                                                <DropdownMenuItem asChild>
                                                                    <ButtonPrimitive
                                                                        menuItem
                                                                        onClick={() => {
                                                                            copyToClipboard(
                                                                                urls.absolute(
                                                                                    urls.currentProject(
                                                                                        urls.ai(conversation.id)
                                                                                    )
                                                                                ),
                                                                                'conversation sharing link'
                                                                            )
                                                                        }}
                                                                    >
                                                                        <IconShare className="size-4 text-tertiary" />
                                                                        Copy link to chat
                                                                    </ButtonPrimitive>
                                                                </DropdownMenuItem>
                                                            </DropdownMenuGroup>
                                                        </DropdownMenuContent>
                                                    </DropdownMenu>
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
