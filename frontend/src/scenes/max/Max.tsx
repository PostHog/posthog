import { BindLogic, useActions, useValues } from 'kea'
import React from 'react'

import { IconArrowLeft, IconChevronLeft, IconClockRewind, IconExternal, IconPlus, IconSidePanel } from '@posthog/icons'
import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { ConversationHistory } from './ConversationHistory'
import { HistoryPreview } from './HistoryPreview'
import { Intro } from './Intro'
import { Thread } from './Thread'
import { AnimatedBackButton } from './components/AnimatedBackButton'
import { SidebarQuestionInput } from './components/SidebarQuestionInput'
import { SidebarQuestionInputWithSuggestions } from './components/SidebarQuestionInputWithSuggestions'
import { ThreadAutoScroller } from './components/ThreadAutoScroller'
import { maxLogic } from './maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from './maxThreadLogic'

export const scene: SceneExport = {
    component: Max,
    logic: maxLogic,
    settingSectionId: 'environment-max',
}

export function Max({ tabId }: { tabId?: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { closeSidePanel } = useActions(sidePanelLogic)
    const { conversationId: tabConversationId } = useValues(maxLogic({ tabId: tabId || '' }))
    const { conversationId: sidepanelConversationId } = useValues(maxLogic({ tabId: 'sidepanel' }))

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    if (sidePanelOpen && selectedTab === SidePanelTab.Max && sidepanelConversationId === tabConversationId) {
        return (
            <SceneContent className="px-4 py-4">
                <SceneTitleSection name={null} resourceType={{ type: 'chat' }} />
                <div className="flex flex-col items-center justify-center w-full grow">
                    <IconSidePanel className="text-3xl text-muted mb-2" />
                    <h3 className="text-xl font-bold mb-1">This chat is currently in the sidebar</h3>
                    <p className="text-sm text-muted mb-2">You can navigate freely around the app, or…</p>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => closeSidePanel()}
                        sideIcon={<IconArrowLeft />}
                    >
                        Move it here
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return <MaxInstance tabId={tabId ?? ''} />
}

export interface MaxInstanceProps {
    sidePanel?: boolean
    tabId: string
}

export const MaxInstance = React.memo(function MaxInstance({ sidePanel, tabId }: MaxInstanceProps): JSX.Element {
    const {
        threadVisible,
        conversationHistoryVisible,
        chatTitle,
        backButtonDisabled,
        threadLogicKey,
        conversation,
        conversationId,
    } = useValues(maxLogic({ tabId }))
    const { startNewConversation, toggleConversationHistory, goBack } = useActions(maxLogic({ tabId }))
    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { closeTabId } = useActions(sceneLogic)

    const threadProps: MaxThreadLogicProps = {
        tabId,
        conversationId: threadLogicKey,
        conversation,
    }

    const { closeSidePanel } = useActions(sidePanelLogic)

    const content = (
        <BindLogic logic={maxLogic} props={{ tabId }}>
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <div
                    style={
                        {
                            // Max has larger border radiuses than rest of the app, for a friendlier, rounder AI vibe
                            display: 'contents',
                        } as React.CSSProperties
                    }
                >
                    {conversationHistoryVisible ? (
                        <ConversationHistory sidePanel={sidePanel} />
                    ) : !threadVisible ? (
                        // pb-7 below is intentionally specific - it's chosen so that the bottom-most chat's title
                        // is at the same viewport height as the QuestionInput text that appear after going into a thread.
                        // This makes the transition from one view into another just that bit smoother visually.
                        <div
                            className={
                                sidePanel
                                    ? '@container/max-welcome relative flex flex-col gap-4 px-4 pb-7 grow'
                                    : '@container/max-welcome relative flex flex-col gap-4 px-4 pb-7 grow min-h-[calc(100vh-var(--scene-layout-header-height)-120px)]'
                            }
                        >
                            <div className="flex-1 items-center justify-center flex flex-col gap-3">
                                <Intro />
                                <SidebarQuestionInputWithSuggestions />
                            </div>
                            <HistoryPreview sidePanel={sidePanel} />
                        </div>
                    ) : (
                        /** Must be the last child and be a direct descendant of the scrollable element */
                        <ThreadAutoScroller>
                            {conversation?.has_unsupported_content && (
                                <div className="px-4 pt-4">
                                    <LemonBanner type="warning">
                                        <div className="flex items-center justify-between gap-4">
                                            <span>This thread contains content that is no longer supported.</span>
                                            <LemonButton type="primary" onClick={() => startNewConversation()}>
                                                Start a new thread
                                            </LemonButton>
                                        </div>
                                    </LemonBanner>
                                </div>
                            )}
                            <Thread className="p-3" />
                            {!conversation?.has_unsupported_content && <SidebarQuestionInput isSticky />}
                        </ThreadAutoScroller>
                    )}
                </div>
            </BindLogic>
        </BindLogic>
    )

    return sidePanel ? (
        <>
            <SidePanelPaneHeader className="transition-all duration-200" onClose={() => startNewConversation()}>
                <div className="flex flex-1">
                    <div className="flex items-center flex-1">
                        <AnimatedBackButton in={!backButtonDisabled}>
                            <LemonButton
                                size="small"
                                icon={<IconChevronLeft />}
                                onClick={() => goBack()}
                                tooltip="Go back"
                                tooltipPlacement="bottom-end"
                                disabledReason={backButtonDisabled ? 'You are already at home' : undefined}
                            />
                        </AnimatedBackButton>

                        <h3
                            className="flex items-center font-semibold mb-0 line-clamp-1 text-sm ml-1 leading-[1.1]"
                            title={chatTitle || undefined}
                        >
                            {chatTitle || (
                                <>
                                    PostHog AI
                                    <LemonTag size="small" type="warning" className="ml-2">
                                        BETA
                                    </LemonTag>
                                </>
                            )}
                        </h3>
                    </div>
                    {!conversationHistoryVisible && !threadVisible && (
                        <LemonButton
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => startNewConversation()}
                            tooltip="Start a new chat"
                            tooltipPlacement="bottom"
                        />
                    )}
                    <LemonButton
                        size="small"
                        sideIcon={<IconExternal />}
                        to={urls.max(conversationId ?? undefined)}
                        onClick={() => {
                            closeSidePanel()
                            startNewConversation()
                        }}
                        targetBlank
                        tooltip="Open as main focus"
                        tooltipPlacement="bottom-end"
                    />
                </div>
            </SidePanelPaneHeader>
            {content}
        </>
    ) : (
        <SceneContent className="px-4 py-4">
            <SceneTitleSection
                name={null}
                resourceType={{ type: 'chat' }}
                actions={
                    conversationId && tabId ? (
                        <LemonButton
                            size="small"
                            type="secondary"
                            sideIcon={<IconSidePanel />}
                            onClick={() => {
                                openSidePanelMax(conversationId)
                                closeTabId(tabId)
                            }}
                        >
                            Open in sidepanel
                        </LemonButton>
                    ) : !conversationHistoryVisible ? (
                        <LemonButton
                            size="small"
                            type="secondary"
                            sideIcon={<IconClockRewind />}
                            onClick={() => toggleConversationHistory()}
                        >
                            Chat history
                        </LemonButton>
                    ) : undefined
                }
            />
            {content}
        </SceneContent>
    )
})
