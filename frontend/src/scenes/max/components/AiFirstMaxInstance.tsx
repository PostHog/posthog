import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { Intro } from '../Intro'
import { Thread } from '../Thread'
import { maxLogic } from '../maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from '../maxThreadLogic'
import { ChatHistoryPanel } from './ChatHistoryPanel'
import { SidebarQuestionInputWithSuggestions } from './SidebarQuestionInputWithSuggestions'

interface AiFirstMaxInstanceProps {
    tabId: string
}

export function AiFirstMaxInstance({ tabId }: AiFirstMaxInstanceProps): JSX.Element {
    const { threadVisible, threadLogicKey, conversation, conversationId } = useValues(maxLogic({ tabId }))
    const { startNewConversation } = useActions(maxLogic({ tabId }))
    const isAIFirst = useFeatureFlag('AI_FIRST')

    const threadProps: MaxThreadLogicProps = {
        tabId,
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        <div className="flex grow overflow-hidden h-full">
            {!isAIFirst && <ChatHistoryPanel tabId={tabId} />}
            <BindLogic logic={maxLogic} props={{ tabId }}>
                <BindLogic logic={maxThreadLogic} props={threadProps}>
                    <ChatArea
                        threadVisible={threadVisible}
                        conversationId={conversationId}
                        conversation={conversation}
                        onStartNewConversation={startNewConversation}
                    />
                </BindLogic>
            </BindLogic>
        </div>
    )
}

interface ChatAreaProps {
    threadVisible: boolean
    conversationId: string | null
    conversation: { has_unsupported_content?: boolean } | null
    onStartNewConversation: () => void
}

function ChatArea({ threadVisible, conversationId, conversation, onStartNewConversation }: ChatAreaProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [stickToBottom, setStickToBottom] = useState(true)
    const { streamingActive } = useValues(maxThreadLogic)

    const hasMessages = threadVisible

    // Scroll to bottom when content changes (streaming or new messages)
    useEffect(() => {
        if (hasMessages && stickToBottom && containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight
        }
    })

    // Track if user scrolled away from bottom
    useEffect(() => {
        const container = containerRef.current
        if (!container || !hasMessages) {
            return
        }

        const handleScroll = (): void => {
            const { scrollTop, scrollHeight, clientHeight } = container
            const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
            setStickToBottom(isAtBottom)
        }

        container.addEventListener('scroll', handleScroll, { passive: true })
        return () => container.removeEventListener('scroll', handleScroll)
    }, [hasMessages])

    // Reset stick-to-bottom when starting a new conversation
    useEffect(() => {
        if (!conversationId) {
            setStickToBottom(true)
        }
    }, [conversationId])

    // Reset stick-to-bottom when streaming starts
    useEffect(() => {
        if (streamingActive) {
            setStickToBottom(true)
        }
    }, [streamingActive])

    return (
        <div ref={containerRef} className="flex flex-col grow overflow-y-auto">
            {/* Top spacer - fills space above content, shrinks when messages appear */}
            <div className={`transition-[flex-grow] duration-300 ease-out ${hasMessages ? 'grow-0' : 'grow'}`} />

            {/* Intro - fades out when messages appear */}
            <div
                className={`flex flex-col items-center transition-all duration-200 ease-out ${
                    hasMessages ? 'opacity-0 h-0 overflow-hidden' : 'opacity-100 pb-3'
                }`}
            >
                <Intro />
            </div>

            {/* Thread content - appears when messages exist */}
            {hasMessages && (
                <>
                    {conversation?.has_unsupported_content && (
                        <div className="px-4 pt-4">
                            <LemonBanner type="warning">
                                <div className="flex items-center justify-between gap-4">
                                    <span>This thread contains content that is no longer supported.</span>
                                    <LemonButton type="primary" onClick={onStartNewConversation}>
                                        Start a new thread
                                    </LemonButton>
                                </div>
                            </LemonBanner>
                        </div>
                    )}
                    <Thread className="p-3" />
                </>
            )}

            {/* Input - always in flow, mt-auto pushes to bottom when messages exist */}
            <div
                className={`w-full max-w-3xl mx-auto px-4 transition-all duration-300 ease-out z-50 ${
                    hasMessages ? 'sticky bottom-0 bg-primary py-2 max-w-none' : 'pb-4'
                }`}
            >
                {!conversation?.has_unsupported_content && (
                    <SidebarQuestionInputWithSuggestions hideSuggestions={hasMessages} />
                )}
            </div>

            {/* Bottom spacer - fills space below content, shrinks when messages appear */}
            <div className={`transition-[flex-grow] duration-300 ease-out ${hasMessages ? 'grow-0' : 'grow'}`} />
        </div>
    )
}
