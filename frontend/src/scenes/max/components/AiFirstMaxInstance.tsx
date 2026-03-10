import { BindLogic, useActions, useValues } from 'kea'

import { IconOpenSidebar, IconShare } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { SceneName } from '~/layout/scenes/components/SceneTitleSection'

import { Intro } from '../Intro'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from '../maxThreadLogic'
import { Thread } from '../Thread'
import { ChatHistoryPanel } from './ChatHistoryPanel'
import { SidebarQuestionInputWithSuggestions } from './SidebarQuestionInputWithSuggestions'
import { ThreadAutoScroller } from './ThreadAutoScroller'

/* Sits above the chat area */
export function ChatHeader({
    conversationId,
    tabId,
    children,
}: {
    conversationId: string | null
    tabId?: string
    children?: React.ReactNode
}): JSX.Element {
    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { chatTitle } = useValues(maxLogic)
    const { closeTabId } = useActions(sceneLogic)
    const isTitleLoading = chatTitle === 'New chat'

    return (
        <div className="flex w-full gap-2 py-2 border-b border-primary items-center justify-between px-2">
            <div className="flex items-center gap-2 pl-2 text-sm font-medium truncate min-w-0 flex-1">
                {children}
                {chatTitle === null ? null : isTitleLoading ? (
                    <div className="w-100">
                        <SceneName name="New chat" isLoading />
                    </div>
                ) : (
                    <SceneName name={chatTitle} />
                )}
            </div>
            <div className="flex items-center gap-2">
                {conversationId ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        sideIcon={<IconShare />}
                        onClick={() => {
                            copyToClipboard(
                                urls.absolute(urls.currentProject(urls.ai(conversationId ?? undefined))),
                                'conversation sharing link'
                            )
                        }}
                    >
                        Copy link
                    </LemonButton>
                ) : undefined}
                {tabId ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        sideIcon={<IconOpenSidebar />}
                        onClick={() => {
                            openSidePanelMax(conversationId ?? undefined)
                            closeTabId(tabId, { source: 'open_in_side_panel' })
                        }}
                    >
                        Open in context panel
                    </LemonButton>
                ) : undefined}
            </div>
        </div>
    )
}

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
                    <div className="flex flex-col grow overflow-hidden">
                        <ChatHeader conversationId={conversationId} tabId={tabId} />
                        <ChatArea
                            threadVisible={threadVisible}
                            conversationId={conversationId}
                            conversation={conversation}
                            onStartNewConversation={startNewConversation}
                        />
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
