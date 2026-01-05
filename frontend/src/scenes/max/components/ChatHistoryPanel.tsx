import { BindLogic, useActions, useValues } from 'kea'
import { memo, useRef } from 'react'

import { IconPlusSmall, IconSidebarClose } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { ConversationHistory } from '../ConversationHistory'
import { maxLogic } from '../maxLogic'
import { CHAT_HISTORY_COLLAPSE_THRESHOLD, maxPanelSizingLogic } from '../maxPanelSizingLogic'

interface ChatHistoryPanelProps {
    tabId: string
}

export const ChatHistoryPanel = memo(function ChatHistoryPanel({ tabId }: ChatHistoryPanelProps): JSX.Element {
    const chatHistoryPanelRef = useRef<HTMLDivElement>(null)
    const { startNewConversation } = useActions(maxLogic({ tabId }))

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
                'relative bg-primary border-r border-primary transition-opacity duration-100 max-w-[var(--chat-history-panel-width)]',
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
            <div className="flex items-center gap-1 w-full p-2 pl-2">
                <ButtonPrimitive
                    onClick={toggleChatHistoryPanelCollapsed}
                    tooltip={isChatHistoryPanelCollapsed ? 'Expand history' : 'Collapse history'}
                    className="shrink-0 z-50 h-[32px]"
                    iconOnly
                >
                    <IconSidebarClose
                        className={cn('size-4 text-tertiary', isChatHistoryPanelCollapsed && 'rotate-180')}
                    />
                </ButtonPrimitive>
                {!isChatHistoryPanelCollapsed && (
                    <>
                        <h3 className="text-sm font-semibold mb-0 flex-1">Chat history</h3>
                        <ButtonPrimitive iconOnly onClick={() => startNewConversation()} tooltip="New chat">
                            <IconPlusSmall />
                        </ButtonPrimitive>
                    </>
                )}
            </div>
            {!isChatHistoryPanelCollapsed && (
                <BindLogic logic={maxLogic} props={{ tabId }}>
                    <ScrollableShadows
                        direction="vertical"
                        className="flex flex-col z-20 h-full"
                        innerClassName="flex flex-col px-2 h-full pb-10"
                        styledScrollbars
                    >
                        <ConversationHistory compact />
                    </ScrollableShadows>
                </BindLogic>
            )}
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
