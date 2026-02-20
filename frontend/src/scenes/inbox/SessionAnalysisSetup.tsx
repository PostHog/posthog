import { BindLogic, useActions, useValues } from 'kea'
import { createContext, useEffect } from 'react'

import { Logomark } from 'lib/brand/Logomark'
import { Thread } from 'scenes/max/Thread'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { inboxSceneLogic } from './inboxSceneLogic'

const INBOX_TAB_ID = 'inbox-setup'

export const InboxSetupContext = createContext<(filters: RecordingUniversalFilters) => void>(undefined as any)

const SUGGESTIONS = ['Just logged-in sessions', 'Sessions where users used our product']

function SessionAnalysisSetupIntro(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center">
            <div className="flex *:h-full *:w-10 p-1">
                <Logomark />
            </div>
            <h3 className="text-base font-bold mb-0.5">Configure session filters</h3>
            <p className="text-xs text-secondary max-w-sm mb-0">
                Describe what sessions to analyze. PostHog AI will help you build the right filters.
            </p>
        </div>
    )
}

function SessionAnalysisSetupSuggestions(): JSX.Element {
    const { askMax } = useActions(maxLogic)

    return (
        <div className="flex flex-wrap gap-1.5 justify-center max-w-md">
            {SUGGESTIONS.map((suggestion) => (
                <button
                    key={suggestion}
                    type="button"
                    className="text-xs px-2.5 py-1 rounded-full border bg-surface-primary hover:bg-surface-secondary transition-colors cursor-pointer"
                    onClick={() => askMax(suggestion)}
                >
                    {suggestion}
                </button>
            ))}
        </div>
    )
}

function SessionAnalysisSetupChat(): JSX.Element {
    const { threadVisible } = useValues(maxLogic)
    const { setAgentMode } = useActions(maxThreadLogic)

    useEffect(() => {
        setAgentMode(AgentMode.SessionReplay)
    }, [setAgentMode])

    const hasMessages = threadVisible

    return (
        <div className="flex flex-col grow overflow-y-auto h-full" data-attr="max-scrollable">
            <div
                className={`flex flex-col items-center gap-3 transition-all duration-200 ease-out ${
                    hasMessages ? 'opacity-0 h-0 overflow-hidden' : 'opacity-100 pb-3'
                }`}
            >
                <SessionAnalysisSetupIntro />
                <SessionAnalysisSetupSuggestions />
            </div>

            {hasMessages && (
                <ThreadAutoScroller>
                    <Thread className="p-3" />
                </ThreadAutoScroller>
            )}

            <div
                className={`w-full max-w-3xl mx-auto px-3 transition-all duration-300 ease-out z-50 ${
                    hasMessages ? 'sticky bottom-0 bg-primary py-2 max-w-none' : ''
                }`}
            >
                <SidebarQuestionInput />
            </div>
        </div>
    )
}

export function SessionAnalysisSetup(): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic({ tabId: INBOX_TAB_ID }))
    const { saveSessionAnalysisFilters } = useActions(inboxSceneLogic)

    return (
        <InboxSetupContext.Provider value={saveSessionAnalysisFilters}>
            <BindLogic logic={maxLogic} props={{ tabId: INBOX_TAB_ID }}>
                <BindLogic
                    logic={maxThreadLogic}
                    props={
                        {
                            tabId: INBOX_TAB_ID,
                            conversationId: threadLogicKey,
                            conversation,
                        } satisfies MaxThreadLogicProps
                    }
                >
                    <SessionAnalysisSetupChat />
                </BindLogic>
            </BindLogic>
        </InboxSetupContext.Provider>
    )
}
