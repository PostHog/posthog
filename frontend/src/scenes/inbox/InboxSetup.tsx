import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { createContext, useEffect, useState } from 'react'

import { IconArrowLeft, IconGithub, IconLinear } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import { RecordingsUniversalFiltersDisplay } from 'lib/components/Cards/InsightCard/RecordingsUniversalFiltersDisplay'
import { IconSlack } from 'lib/lemon-ui/icons'
import { Thread } from 'scenes/max/Thread'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { inboxSceneLogic } from './inboxSceneLogic'

const INBOX_TAB_ID = 'inbox-setup'

export const InboxSetupContext = createContext<(filters: RecordingUniversalFilters) => void>()

const SUGGESTIONS = [
    'Sessions with console errors from the last 7 days',
    'Sessions from US users on mobile devices',
    'Sessions longer than 5 minutes with rage clicks',
    'Sessions where users visited the pricing page',
]

// --- Sources list view ---

type SourceProps =
    | {
          icon: React.ReactNode
          title: string
          description: string
          variant: 'coming-soon'
      }
    | {
          icon: React.ReactNode
          title: string
          description: string
          variant: 'available'
          checked: boolean
          onToggle: () => void
          configSection: React.ReactNode
          configButtonLabel: string
          onConfigClick: () => void
      }

function NotifyMeButton({ source }: { source: string }): JSX.Element {
    const [notified, setNotified] = useState(false)

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            disabledReason={notified ? "We'll let you know!" : undefined}
            onClick={() => {
                posthog.capture('signals source interest', { source })
                setNotified(true)
            }}
            className="-my-4" // Prevent the button's height from affecting the row's height
        >
            {notified ? "We'll notify you!" : 'Notify me when available'}
        </LemonButton>
    )
}

function Source(props: SourceProps): JSX.Element {
    const isComingSoon = props.variant === 'coming-soon'

    return (
        <div className="flex gap-3 pb-3 last:pb-0 px-1 items-start">
            <div className="shrink-0 mt-2">{props.icon}</div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-sm">{props.title}</div>
                    {isComingSoon ? (
                        <NotifyMeButton source={props.title} />
                    ) : (
                        <LemonSwitch checked={props.checked} onChange={props.onToggle} />
                    )}
                </div>
                <p className="text-xs text-secondary mt-0.25 mb-0">{props.description}</p>
                {!isComingSoon && props.checked && (
                    <div className="mt-2 border rounded">
                        <div className="flex items-center justify-between px-2 pt-2">
                            <span className="text-xs font-semibold text-secondary">Filters</span>
                            <LemonButton type="secondary" size="xsmall" onClick={props.onConfigClick}>
                                {props.configButtonLabel}
                            </LemonButton>
                        </div>
                        {props.configSection}
                    </div>
                )}
            </div>
        </div>
    )
}

function SourcesList(): JSX.Element {
    const { hasSessionAnalysisSource, sessionAnalysisConfig } = useValues(inboxSceneLogic)
    const { toggleSessionAnalysis, openSessionAnalysisSetup } = useActions(inboxSceneLogic)

    const recordingFilters = sessionAnalysisConfig?.config?.recording_filters

    return (
        <div className="divide-y space-y-3">
            <Source
                icon={
                    <div className="flex *:text-xl group/colorful-product-icons colorful-product-icons-true">
                        {iconForType('session_replay')}
                    </div>
                }
                title="PostHog Session Replay"
                description="Session recordings + event data → Signals"
                variant="available"
                checked={hasSessionAnalysisSource}
                onToggle={() => toggleSessionAnalysis()}
                configButtonLabel={recordingFilters ? 'Edit' : 'Configure'}
                onConfigClick={openSessionAnalysisSetup}
                configSection={
                    recordingFilters ? (
                        <RecordingsUniversalFiltersDisplay filters={recordingFilters} />
                    ) : (
                        <div className="px-2 pb-2">
                            <span className="text-xs text-secondary">All sessions</span>
                        </div>
                    )
                }
            />

            <Source
                icon={
                    <svg className="size-5" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M11.2 2v14.4L2 22V7.6A5.6 5.6 0 0 1 7.6 2h3.6ZM12.8 7.6 22 2v14.4a5.6 5.6 0 0 1-5.6 5.6h-3.6V7.6Z" />
                    </svg>
                }
                title="Zendesk"
                description="Incoming support tickets → Signals"
                variant="coming-soon"
            />

            <Source
                icon={<IconLinear className="size-5" />}
                title="Linear"
                description="New issues and updates → Signals"
                variant="coming-soon"
            />

            <Source
                icon={<IconGithub className="size-5" />}
                title="GitHub Issues"
                description="New issues and updates → Signals"
                variant="coming-soon"
            />

            <Source
                icon={<IconSlack className="size-5 grayscale" />}
                title="Slack"
                description="Messages and threads from channels → Signals"
                variant="coming-soon"
            />
        </div>
    )
}

// --- Session analysis Max chat setup ---

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
        <div className="flex flex-col grow overflow-y-auto" data-attr="max-scrollable">
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
                    hasMessages ? 'sticky bottom-0 bg-primary py-2 max-w-none' : 'pb-3'
                }`}
            >
                <SidebarQuestionInput />
            </div>
        </div>
    )
}

function SessionAnalysisSetup(): JSX.Element {
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

// --- Modal ---

export function SourcesModal(): JSX.Element {
    const { sourcesModalOpen, sessionAnalysisSetupOpen } = useValues(inboxSceneLogic)
    const { closeSourcesModal, closeSessionAnalysisSetup } = useActions(inboxSceneLogic)

    return (
        <LemonModal
            isOpen={sourcesModalOpen}
            onClose={closeSourcesModal}
            simple
            width={sessionAnalysisSetupOpen ? '48rem' : '32rem'}
        >
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    {sessionAnalysisSetupOpen && (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={closeSessionAnalysisSetup}
                        />
                    )}
                    <h3 className="font-semibold mb-0">
                        {sessionAnalysisSetupOpen ? 'Session analysis filters' : 'Signal sources'}
                    </h3>
                </div>
                {!sessionAnalysisSetupOpen && (
                    <p className="text-xs text-secondary mt-1 mb-0">Set up sources feeding the Inbox.</p>
                )}
            </LemonModal.Header>
            <LemonModal.Content>
                {sessionAnalysisSetupOpen ? (
                    <div className="flex flex-col h-[28rem]">
                        <SessionAnalysisSetup />
                    </div>
                ) : (
                    <SourcesList />
                )}
            </LemonModal.Content>
        </LemonModal>
    )
}
