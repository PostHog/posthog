import { BindLogic, useActions, useValues } from 'kea'
import { createContext, useEffect } from 'react'

import { Logomark } from 'lib/brand/Logomark'
import { Thread } from 'scenes/max/Thread'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

const INBOX_TAB_ID = 'inbox-setup'

export const InboxSetupContext = createContext<boolean>(false)

const SUGGESTIONS = [
    'Sessions with console errors from the last 7 days',
    'Sessions from US users on mobile devices',
    'Sessions longer than 5 minutes with rage clicks',
    'Sessions where users visited the pricing page',
]

function InboxSetupIntro(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center">
            <div className="flex *:h-full *:w-12 p-2">
                <Logomark />
            </div>
            <h2 className="text-lg font-bold mb-1">Set up session analysis</h2>
            <p className="text-sm text-secondary max-w-md mb-0">
                Describe what sessions you'd like to analyze for actionable reports. PostHog AI will help you build the
                right filters.
            </p>
        </div>
    )
}

function InboxSetupSuggestions(): JSX.Element {
    const { askMax } = useActions(maxLogic)

    return (
        <div className="flex flex-wrap gap-2 justify-center max-w-lg">
            {SUGGESTIONS.map((suggestion) => (
                <button
                    key={suggestion}
                    type="button"
                    className="text-xs px-3 py-1.5 rounded-full border bg-surface-primary hover:bg-surface-secondary transition-colors cursor-pointer"
                    onClick={() => askMax(suggestion)}
                >
                    {suggestion}
                </button>
            ))}
        </div>
    )
}

function InboxSetupChat(): JSX.Element {
    const { threadVisible } = useValues(maxLogic)
    const { setAgentMode } = useActions(maxThreadLogic)

    useEffect(() => {
        setAgentMode(AgentMode.SessionReplay)
    }, [setAgentMode])

    const hasMessages = threadVisible

    return (
        <div className="flex flex-col grow overflow-y-auto" data-attr="max-scrollable">
            <div className={`transition-[flex-grow] duration-300 ease-out ${hasMessages ? 'grow-0' : 'grow'}`} />

            <div
                className={`flex flex-col items-center gap-4 transition-all duration-200 ease-out ${
                    hasMessages ? 'opacity-0 h-0 overflow-hidden' : 'opacity-100 pb-3'
                }`}
            >
                <InboxSetupIntro />
                <InboxSetupSuggestions />
            </div>

            {hasMessages && (
                <ThreadAutoScroller>
                    <Thread className="p-3" />
                </ThreadAutoScroller>
            )}

            <div
                className={`w-full max-w-3xl mx-auto px-4 transition-all duration-300 ease-out z-50 ${
                    hasMessages ? 'sticky bottom-0 bg-primary py-2 max-w-none' : 'pb-4'
                }`}
            >
                <SidebarQuestionInput />
            </div>

            <div className={`transition-[flex-grow] duration-300 ease-out ${hasMessages ? 'grow-0' : 'grow'}`} />
        </div>
    )
}

export function InboxSetup(): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic({ tabId: INBOX_TAB_ID }))

    const threadProps: MaxThreadLogicProps = {
        tabId: INBOX_TAB_ID,
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        <InboxSetupContext.Provider value={true}>
            <div className="flex flex-col grow overflow-hidden border rounded-lg bg-surface-primary">
                <BindLogic logic={maxLogic} props={{ tabId: INBOX_TAB_ID }}>
                    <BindLogic logic={maxThreadLogic} props={threadProps}>
                        <InboxSetupChat />
                    </BindLogic>
                </BindLogic>
            </div>
        </InboxSetupContext.Provider>
    )
}
