import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { EmbeddedRunner } from 'products/posthog_ai/frontend/api/runner'

import { Intro } from '../Intro'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from '../maxThreadLogic'
import { Thread } from '../Thread'
import { ChatHeader } from './ChatHeader'
import { MaxNotConfigured } from './MaxNotConfigured'
import { PhaiViewToggle } from './PhaiViewToggle'
import { SidebarQuestionInputWithSuggestions } from './SidebarQuestionInputWithSuggestions'
import { ThreadAutoScroller } from './ThreadAutoScroller'

interface AiFirstMaxInstanceProps {
    tabId: string
}

export function AiFirstMaxInstance({ tabId }: AiFirstMaxInstanceProps): JSX.Element {
    const { threadVisible, threadLogicKey, conversation, conversationId } = useValues(maxLogic({ panelId: tabId }))
    const { startNewConversation } = useActions(maxLogic({ panelId: tabId }))
    const { isMaxAvailable, effectivePhaiView } = useValues(maxGlobalLogic)

    // On `/ai` the new view is the full TaskTracker product (tasks list + composer + run detail); a thin
    // bar keeps the toggle reachable so the user can drop back to the legacy chat.
    if (effectivePhaiView === 'new') {
        return (
            <div className="flex flex-col grow overflow-hidden h-full">
                <div className="flex w-full items-center justify-end gap-2 py-2 px-2 border-b border-primary">
                    <PhaiViewToggle variant="lemon" />
                </div>
                <div className="flex flex-col flex-1 min-h-0">
                    <EmbeddedRunner />
                </div>
            </div>
        )
    }

    const threadProps: MaxThreadLogicProps = {
        panelId: tabId,
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        <div className="flex grow overflow-hidden h-full">
            <BindLogic logic={maxLogic} props={{ panelId: tabId }}>
                <BindLogic logic={maxThreadLogic} props={threadProps}>
                    <div className="flex flex-col grow overflow-hidden">
                        <ChatHeader conversationId={conversationId} tabId={tabId} />
                        {isMaxAvailable ? (
                            <ChatArea
                                threadVisible={threadVisible}
                                conversationId={conversationId}
                                conversation={conversation}
                                onStartNewConversation={startNewConversation}
                            />
                        ) : (
                            <MaxNotConfigured />
                        )}
                    </div>
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
                className={`flex flex-col items-center transition-[opacity,height,padding] duration-200 ease-out ${
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
                className={`w-full max-w-3xl mx-auto px-4 transition-[max-width,padding,background-color] duration-300 ease-out z-50 ${
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
