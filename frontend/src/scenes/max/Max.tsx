import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import React from 'react'

import { IconArrowLeft, IconChevronLeft, IconClockRewind, IconExternal, IconPlus, IconSidePanel } from '@posthog/icons'
import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
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
    const { sidePanelTabId } = useValues(maxGlobalLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    if (sidePanelOpen && selectedTab === SidePanelTab.Max && sidePanelTabId === tabId) {
        return (
            <div className="flex flex-col items-center justify-center w-full grow">
                <IconSidePanel className="text-3xl text-muted mb-2" />
                <h3 className="text-xl font-bold mb-1">Max is currently in the sidebar</h3>
                <p className="text-sm text-muted mb-2">You can navigate freely around the app, or…</p>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => closeSidePanel()}
                    sideIcon={<IconArrowLeft />}
                >
                    Get him in here
                </LemonButton>
            </div>
        )
    }

    return <MaxInstance tabId={tabId ?? ''} />
}

export interface MaxInstanceProps {
    sidePanel?: boolean
    tabId: string
}

export const MaxInstance = React.memo(function MaxInstance({ sidePanel, tabId }: MaxInstanceProps): JSX.Element {
    const { threadVisible, conversationHistoryVisible, chatTitle, backButtonDisabled, threadLogicKey, conversation } =
        useValues(maxLogic({ tabId }))
    const { startNewConversation, toggleConversationHistory, goBack } = useActions(maxLogic({ tabId }))

    const threadProps: MaxThreadLogicProps = {
        tabId,
        conversationId: threadLogicKey,
        conversation,
    }
    // Connect the specific thread to the specific max tab
    useMountedLogic(maxThreadLogic(threadProps))
    useAttachedLogic(maxThreadLogic(threadProps), maxLogic({ tabId }))

    const { closeSidePanel } = useActions(sidePanelLogic)

    const headerButtons = (
        <>
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
                sideIcon={<IconClockRewind />}
                onClick={() => toggleConversationHistory()}
                tooltip="Open chat history"
                tooltipPlacement="bottom"
            />
        </>
    )

    return (
        <>
            {sidePanel && (
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
                            {chatTitle ? (
                                <h3
                                    className="flex items-center font-semibold mb-0 line-clamp-1 text-sm ml-1 leading-[1.1]"
                                    title={chatTitle !== 'Max AI' ? chatTitle : undefined}
                                >
                                    {chatTitle !== 'Max AI' ? (
                                        chatTitle
                                    ) : (
                                        <>
                                            Max AI
                                            <LemonTag size="small" type="warning" className="ml-2">
                                                BETA
                                            </LemonTag>
                                        </>
                                    )}
                                </h3>
                            ) : (
                                <LemonSkeleton className="h-5 w-48 ml-1" />
                            )}
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
                            to={urls.max()}
                            onClick={() => closeSidePanel()}
                            tooltip="Open as main focus"
                            tooltipPlacement="bottom-end"
                        />
                    </div>
                </SidePanelPaneHeader>
            )}
            {!sidePanel && <div className="flex justify-end gap-2 pt-1 px-4">{headerButtons}</div>}

            <BindLogic logic={maxLogic} props={{ tabId }}>
                <BindLogic logic={maxThreadLogic} props={threadProps}>
                    {conversationHistoryVisible ? (
                        <ConversationHistory sidePanel={sidePanel} />
                    ) : !threadVisible ? (
                        // pb-7 below is intentionally specific - it's chosen so that the bottom-most chat's title
                        // is at the same viewport height as the QuestionInput text that appear after going into a thread.
                        // This makes the transition from one view into another just that bit smoother visually.
                        <div className="@container/max-welcome relative flex flex-col gap-4 px-4 pb-7 grow min-h-[calc(100vh-var(--scene-layout-header-height))]">
                            <div className="flex-1 items-center justify-center flex flex-col gap-3">
                                <Intro />
                                <SidebarQuestionInputWithSuggestions />
                            </div>
                            <HistoryPreview sidePanel={sidePanel} />
                        </div>
                    ) : (
                        /** Must be the last child and be a direct descendant of the scrollable element */
                        <ThreadAutoScroller>
                            <Thread className="p-3" />
                            <SidebarQuestionInput isSticky />
                        </ThreadAutoScroller>
                    )}
                </BindLogic>
            </BindLogic>
        </>
    )
})
