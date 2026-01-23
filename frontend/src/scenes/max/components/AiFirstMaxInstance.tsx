import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

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

    const threadProps: MaxThreadLogicProps = {
        tabId,
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        <div className="flex grow overflow-hidden h-full">
            <ChatHistoryPanel tabId={tabId} />
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
    const bottomSentinelRef = useRef<HTMLDivElement>(null)
    const inputContainerRef = useRef<HTMLDivElement>(null)
    const lastHumanMessageNodeRef = useRef<HTMLDivElement | null>(null)
    const [showScrollButton, setShowScrollButton] = useState(false)
    const [pendingScroll, setPendingScroll] = useState(false)
    const [responseMinHeight, setResponseMinHeight] = useState<number>(0)
    const { threadGrouped, streamingActive } = useValues(maxThreadLogic)
    const prevHumanMessageCount = useRef(0)

    const hasMessages = threadVisible

    // Count human messages in the thread
    const humanMessageCount = threadGrouped.filter((msg) => msg.type === 'human').length

    // Scroll to bottom handler
    const handleScrollToBottom = useCallback((): void => {
        if (containerRef.current) {
            containerRef.current.scrollTo({
                top: containerRef.current.scrollHeight,
                behavior: 'smooth',
            })
        }
    }, [])

    // Track when a new human message is sent
    useEffect(() => {
        if (humanMessageCount > prevHumanMessageCount.current) {
            setPendingScroll(true)
        }
        prevHumanMessageCount.current = humanMessageCount
    }, [humanMessageCount])

    // Perform scroll and calculate response min-height when new message is sent
    useEffect(() => {
        if (pendingScroll && lastHumanMessageNodeRef.current && containerRef.current) {
            setPendingScroll(false)
            const node = lastHumanMessageNodeRef.current
            const container = containerRef.current

            // Use requestAnimationFrame to ensure layout is complete
            requestAnimationFrame(() => {
                const containerHeight = container.clientHeight
                const messageHeight = node.offsetHeight
                const inputHeight = inputContainerRef.current?.offsetHeight ?? 0

                // Calculate min-height for AI response: container - human message - input - padding
                const minHeight = containerHeight - messageHeight - inputHeight - 32
                setResponseMinHeight(Math.max(0, minHeight))

                // Scroll so human message is at top
                const containerRect = container.getBoundingClientRect()
                const nodeRect = node.getBoundingClientRect()
                const scrollOffset = nodeRect.top - containerRect.top + container.scrollTop

                container.scrollTo({
                    top: scrollOffset - 16, // 16px padding from top
                    behavior: 'smooth',
                })
            })
        }
    }, [pendingScroll])

    // Callback ref to capture the last human message node
    const lastHumanMessageRef = useCallback((node: HTMLDivElement | null): void => {
        lastHumanMessageNodeRef.current = node
    }, [])

    // Track if there's content below the viewport using IntersectionObserver
    useEffect(() => {
        const sentinel = bottomSentinelRef.current
        const container = containerRef.current
        if (!sentinel || !container || !hasMessages) {
            return
        }

        const observer = new IntersectionObserver(
            ([entry]) => {
                // Show button when sentinel is NOT visible (content below viewport)
                setShowScrollButton(!entry.isIntersecting)
            },
            {
                root: container,
                threshold: 0,
                rootMargin: '0px',
            }
        )

        observer.observe(sentinel)
        return () => observer.disconnect()
    }, [hasMessages])

    // Reset scroll button when starting a new conversation
    useEffect(() => {
        if (!conversationId) {
            setShowScrollButton(false)
            prevHumanMessageCount.current = 0
        }
    }, [conversationId])

    // Find the index of the last human message to attach ref
    const lastHumanMessageIndex = threadGrouped.reduce(
        (lastIndex, msg, index) => (msg.type === 'human' ? index : lastIndex),
        -1
    )

    return (
        <div ref={containerRef} className="flex flex-col grow overflow-y-auto relative">
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
                    <Thread
                        className="p-3"
                        lastHumanMessageRef={lastHumanMessageRef}
                        lastHumanMessageIndex={lastHumanMessageIndex}
                        responseMinHeight={responseMinHeight}
                    />
                </>
            )}

            {/* Bottom sentinel - used to detect if there's content below the viewport */}
            <div ref={bottomSentinelRef} className="h-px w-full shrink-0" />

            {/* Input area with scroll button */}
            <div
                ref={inputContainerRef}
                className={`w-full max-w-3xl mx-auto px-4 transition-all duration-300 ease-out z-50 ${
                    hasMessages ? 'sticky bottom-0 bg-primary py-2 max-w-none' : 'pb-4'
                }`}
            >
                {/* Scroll to bottom button - appears above input when content overflows */}
                {showScrollButton && hasMessages && (
                    <div className="flex justify-center mb-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconChevronDown />}
                            onClick={handleScrollToBottom}
                            className="shadow-md"
                        >
                            {streamingActive ? 'Scroll to response' : 'Scroll to bottom'}
                        </LemonButton>
                    </div>
                )}
                {!conversation?.has_unsupported_content && (
                    <SidebarQuestionInputWithSuggestions hideSuggestions={hasMessages} />
                )}
            </div>

            {/* Bottom spacer - fills space below content, shrinks when messages appear */}
            <div className={`transition-[flex-grow] duration-300 ease-out ${hasMessages ? 'grow-0' : 'grow'}`} />
        </div>
    )
}
