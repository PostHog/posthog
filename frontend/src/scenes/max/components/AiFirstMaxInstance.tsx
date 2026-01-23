import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

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
    const inputContainerRef = useRef<HTMLDivElement>(null)
    const lastHumanMessageNodeRef = useRef<HTMLDivElement | null>(null)
    const [showScrollButton, setShowScrollButton] = useState(false)
    const [pendingScroll, setPendingScroll] = useState(false)
    const [responseMinHeight, setResponseMinHeight] = useState<number>(0)
    const { threadGrouped } = useValues(maxThreadLogic)
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

                // AI response wrapper min-height = container - human message - input
                // Human message at top, AI responses fill middle, input at bottom
                const minHeight = containerHeight - messageHeight - inputHeight
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

    // Track content overflow and manage scroll button + min-height
    useEffect(() => {
        const container = containerRef.current
        if (!container || !hasMessages) {
            return
        }

        const checkContentOverflow = (): void => {
            const hasOverflow = container.scrollHeight > container.clientHeight + 5

            // If content overflows, remove min-height (it's no longer needed)
            if (hasOverflow && responseMinHeight > 0) {
                setResponseMinHeight(0)
            }

            // Show scroll button only when there's real overflow AND not at bottom
            if (hasOverflow) {
                const scrollBottom = container.scrollTop + container.clientHeight
                const isAtBottom = scrollBottom >= container.scrollHeight - 20
                setShowScrollButton(!isAtBottom)
            } else {
                setShowScrollButton(false)
            }
        }

        // Check initially and on scroll
        checkContentOverflow()
        container.addEventListener('scroll', checkContentOverflow)

        // Watch for content size changes
        const mutationObserver = new MutationObserver(checkContentOverflow)
        mutationObserver.observe(container, {
            childList: true,
            subtree: true,
            characterData: true,
        })

        // ResizeObserver for container size changes
        const resizeObserver = new ResizeObserver(checkContentOverflow)
        resizeObserver.observe(container)

        return () => {
            container.removeEventListener('scroll', checkContentOverflow)
            mutationObserver.disconnect()
            resizeObserver.disconnect()
        }
    }, [hasMessages, responseMinHeight])

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

            {/* Input area wrapper for sticky positioning */}
            <div className={`${hasMessages ? 'sticky bottom-0' : ''} z-50`}>
                <div className="h-0 w-full">
                    <div
                        className={`
                            flex justify-center pb-2 bg-gradient-to-t from-primary to-transparent pt-4 w-full
                            transition-all duration-300
                            ${showScrollButton && hasMessages ? 'opacity-100 pointer-events-auto -translate-y-full' : 'opacity-0 pointer-events-none translate-y-4'}
                        `}
                        style={{ position: 'static' }}
                    >
                        <ButtonPrimitive
                            onClick={handleScrollToBottom}
                            className="shadow-md bg-surface-primary rounded-full"
                        >
                            <IconChevronDown />
                        </ButtonPrimitive>
                    </div>
                </div>
                {/* Scroll to bottom button - above input */}

                {/* Input container */}
                <div
                    ref={inputContainerRef}
                    className={`w-full max-w-3xl mx-auto transition-all duration-300 ease-out ${
                        hasMessages ? 'bg-primary pb-2 max-w-none' : 'pb-4'
                    }`}
                >
                    {!conversation?.has_unsupported_content && (
                        <SidebarQuestionInputWithSuggestions hideSuggestions={hasMessages} />
                    )}
                </div>
            </div>

            {/* Bottom spacer - fills space below content, shrinks when messages appear */}
            <div className={`transition-[flex-grow] duration-300 ease-out ${hasMessages ? 'grow-0' : 'grow'}`} />
        </div>
    )
}
