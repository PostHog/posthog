import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React from 'react'

import {
    IconArrowLeft,
    IconChevronLeft,
    IconExpand45,
    IconLock,
    IconOpenSidebar,
    IconPlus,
    IconShare,
    IconSidePanel,
} from '@posthog/icons'
import { LemonBanner, Link, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { appLogic } from 'scenes/appLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SidePanelContentContainer } from '~/layout/navigation-3000/sidepanel/SidePanelContentContainer'
import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { ConversationHistory } from './ConversationHistory'
import { HistoryPreview } from './HistoryPreview'
import { Intro } from './Intro'
import { Thread } from './Thread'
import { AiFirstMaxInstance } from './components/AiFirstMaxInstance'
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
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { closeSidePanel } = useActions(sidePanelLogic)
    const { conversationId: tabConversationId } = useValues(maxLogic({ tabId: tabId || '' }))
    const { conversationId: sidepanelConversationId } = useValues(maxLogic({ tabId: 'sidepanel' }))
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    if (sidePanelOpen && selectedTab === SidePanelTab.Max && sidepanelConversationId === tabConversationId) {
        return (
            <SceneContent className="px-4 py-4 min-h-[calc(100vh-var(--scene-layout-header-height)-120px)]">
                <SceneTitleSection name={null} resourceType={{ type: 'chat' }} />
                <div className="flex flex-col items-center justify-center w-full grow">
                    <IconSidePanel className="text-3xl text-muted mb-2" />
                    <h3 className="text-xl font-bold mb-1">The chat is currently in the sidebar</h3>
                    <p className="text-sm text-muted mb-2">You can navigate freely around the app with it, or…</p>
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

    if (isRemovingSidePanelFlag) {
        return <AiFirstMaxInstance tabId={tabId ?? ''} />
    }

    return <MaxInstance tabId={tabId ?? ''} />
}

export interface MaxInstanceProps {
    sidePanel?: boolean
    tabId: string
    isAIOnlyMode?: boolean
}

export const MaxInstance = React.memo(function MaxInstance({
    sidePanel,
    tabId,
    isAIOnlyMode,
}: MaxInstanceProps): JSX.Element {
    const {
        threadVisible,
        conversationHistoryVisible,
        chatTitle,
        backButtonDisabled,
        threadLogicKey,
        conversation,
        conversationId,
    } = useValues(maxLogic({ tabId }))
    const { startNewConversation, goBack } = useActions(maxLogic({ tabId }))
    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { closeTabId } = useActions(sceneLogic)
    const { exitAIOnlyMode } = useActions(appLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    const threadProps: MaxThreadLogicProps = {
        tabId,
        conversationId: threadLogicKey,
        conversation,
    }

    const { closeSidePanel } = useActions(sidePanelLogic)

    const content = (
        <BindLogic logic={maxLogic} props={{ tabId }}>
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                {conversationHistoryVisible ? (
                    <ConversationHistory sidePanel={sidePanel} />
                ) : !threadVisible ? (
                    // pb-7 below is intentionally specific - it's chosen so that the bottom-most chat's title
                    // is at the same viewport height as the QuestionInput text that appear after going into a thread.
                    // This makes the transition from one view into another just that bit smoother visually.
                    <div
                        className={clsx(
                            '@container/max-welcome relative flex flex-col gap-4 px-4 pb-7 grow',
                            !sidePanel && 'min-h-[calc(100vh-var(--scene-layout-header-height)-120px)]'
                        )}
                    >
                        <div className="flex-1 items-center justify-center flex flex-col gap-3 relative z-50">
                            <Intro />
                            <SidebarQuestionInputWithSuggestions />
                        </div>

                        {!isRemovingSidePanelFlag && <HistoryPreview sidePanel={sidePanel} />}
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
            </BindLogic>
        </BindLogic>
    )

    return sidePanel ? (
        <>
            <SidePanelPaneHeader
                className="transition-all duration-200"
                onClose={() => {
                    exitAIOnlyMode()
                    startNewConversation()
                }}
            >
                <div className="flex flex-1 min-w-0 overflow-hidden">
                    <div className="flex items-center flex-1 min-w-0">
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

                        <Tooltip title={chatTitle || undefined} placement="bottom">
                            <h3 className="flex-1 font-semibold mb-0 truncate text-sm ml-1">
                                {chatTitle || 'PostHog AI'}
                            </h3>
                        </Tooltip>
                    </div>
                    {conversationId && !conversationHistoryVisible && !threadVisible && !isAIOnlyMode && (
                        <LemonButton
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => startNewConversation()}
                            tooltip="Start a new chat"
                            tooltipPlacement="bottom"
                        />
                    )}
                    {conversationId && (
                        <>
                            {isRemovingSidePanelFlag ? (
                                <ButtonPrimitive
                                    onClick={() => {
                                        copyToClipboard(
                                            urls.absolute(urls.currentProject(urls.ai(conversationId))),
                                            'conversation sharing link'
                                        )
                                    }}
                                    tooltip="Copy link to chat"
                                    tooltipPlacement="bottom-end"
                                    iconOnly
                                >
                                    <IconShare className="text-tertiary size-3 group-hover:text-primary z-10" />
                                </ButtonPrimitive>
                            ) : (
                                <LemonButton
                                    size="small"
                                    icon={<IconShare />}
                                    onClick={() => {
                                        copyToClipboard(
                                            urls.absolute(urls.currentProject(urls.ai(conversationId))),
                                            'conversation sharing link'
                                        )
                                    }}
                                    tooltip={
                                        <>
                                            Copy link to chat
                                            <br />
                                            <em>
                                                <IconLock /> Requires organization access
                                            </em>
                                        </>
                                    }
                                    tooltipPlacement="bottom-end"
                                />
                            )}
                        </>
                    )}
                    {isRemovingSidePanelFlag ? (
                        <Link
                            buttonProps={{
                                iconOnly: true,
                            }}
                            to={urls.ai(conversationId ?? undefined)}
                            onClick={() => {
                                closeSidePanel()
                            }}
                            target="_blank"
                            tooltip="Open as main focus"
                            tooltipPlacement="bottom-end"
                        >
                            <IconExpand45 className="text-tertiary size-3 group-hover:text-primary z-10" />
                        </Link>
                    ) : (
                        <LemonButton
                            size="small"
                            sideIcon={<IconExpand45 />}
                            to={urls.ai(conversationId ?? undefined)}
                            onClick={() => {
                                closeSidePanel()
                                startNewConversation()
                            }}
                            targetBlank
                            tooltip="Open as main focus"
                            tooltipPlacement="bottom-end"
                        />
                    )}
                </div>
            </SidePanelPaneHeader>
            <SidePanelContentContainer flagOffClassName="contents">{content}</SidePanelContentContainer>
        </>
    ) : (
        <SceneContent className="pt-4 px-4 min-h-[calc(100vh-var(--scene-layout-header-height))]">
            <SceneTitleSection
                name={null}
                resourceType={{ type: 'chat' }}
                actions={
                    <>
                        {tabId && conversationId ? (
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
                                Copy link to chat
                            </LemonButton>
                        ) : undefined}
                        {tabId ? (
                            <LemonButton
                                size="small"
                                type="secondary"
                                sideIcon={<IconOpenSidebar />}
                                onClick={() => {
                                    openSidePanelMax(conversationId ?? undefined)
                                    closeTabId(tabId)
                                }}
                            >
                                Open in side panel
                            </LemonButton>
                        ) : undefined}
                    </>
                }
            />
            <div className="grow flex flex-col">{content}</div>
        </SceneContent>
    )
})
