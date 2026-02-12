import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { Intro } from '../Intro'
import { Thread } from '../Thread'
import { maxLogic } from '../maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from '../maxThreadLogic'
import { ChatHistoryPanel } from './ChatHistoryPanel'
import { SidebarQuestionInputWithSuggestions } from './SidebarQuestionInputWithSuggestions'
import { ThreadAutoScroller } from './ThreadAutoScroller'

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

function ChatArea({ threadVisible, conversation, onStartNewConversation }: ChatAreaProps): JSX.Element {
    const hasMessages = threadVisible

    return (
        <div className="flex flex-col grow overflow-y-auto" data-attr="max-scrollable">
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
                <ThreadAutoScroller>
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
                </ThreadAutoScroller>
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
