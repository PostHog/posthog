import {
    IconArrowLeft,
    IconChevronLeft,
    IconClockRewind,
    IconExternal,
    IconCornerDownRight,
    IconMinus,
    IconPlus,
    IconSidePanel,
} from '@posthog/icons'
import { LemonBanner, LemonTag, Link } from '@posthog/lemon-ui'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useEffect, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { AnimatedBackButton } from './components/AnimatedBackButton'
import { SidebarQuestionInput } from './components/SidebarQuestionInput'
import { SidebarQuestionInputWithSuggestions } from './components/SidebarQuestionInputWithSuggestions'
import { ThreadAutoScroller } from './components/ThreadAutoScroller'
import { ConversationHistory } from './ConversationHistory'
import { HistoryPreview } from './HistoryPreview'
import { Intro } from './Intro'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import { Thread } from './Thread'
import clsx from 'clsx'
import { IconArrowUp } from 'lib/lemon-ui/icons'

export const scene: SceneExport = {
    component: Max,
    logic: maxGlobalLogic,
    settingSectionId: 'environment-max',
}

export function Max(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { isFloatingMaxExpanded, floatingMaxPosition } = useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { closeSidePanel } = useActions(sidePanelLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    if (isFloatingMaxExpanded || (sidePanelOpen && selectedTab === SidePanelTab.Max)) {
        return (
            <div className="flex flex-col items-center justify-center w-full grow">
                {isFloatingMaxExpanded ? (
                    <IconCornerDownRight
                        className={clsx(
                            'text-3xl text-muted mb-2',
                            floatingMaxPosition?.side === 'left' && '-scale-x-100'
                        )}
                    />
                ) : (
                    <IconSidePanel className="text-3xl text-muted mb-2" />
                )}
                <h3 className="text-xl font-bold mb-1">
                    Max is currently {isFloatingMaxExpanded ? 'floating' : 'in the sidebar'}
                </h3>
                <p className="text-sm text-muted mb-2">You can navigate freely around the app, or…</p>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => (isFloatingMaxExpanded ? setIsFloatingMaxExpanded(false) : closeSidePanel())}
                    sideIcon={isFloatingMaxExpanded ? <IconArrowUp /> : <IconArrowLeft />}
                >
                    Get him in here
                </LemonButton>
            </div>
        )
    }

    return <MaxInstance />
}

export interface MaxInstanceProps {
    sidePanel?: boolean
}

export const MaxInstance = React.memo(function MaxInstance({ sidePanel }: MaxInstanceProps): JSX.Element {
    const { threadVisible, conversationHistoryVisible, chatTitle, backButtonDisabled, threadLogicKey, conversation } =
        useValues(maxLogic)
    const { startNewConversation, toggleConversationHistory, goBack } = useActions(maxLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    const { closeSidePanel } = useActions(sidePanelLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const { currentLocation } = useValues(router)

    const [wasUserAutoEnrolled, setWasUserAutoEnrolled] = useState(false)
    useEffect(() => {
        if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
            updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.ARTIFICIAL_HOG, true)
            setWasUserAutoEnrolled(true)
        }
    }, [featureFlags, updateEarlyAccessFeatureEnrollment])

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
            {featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG] && (
                <LemonButton
                    size="small"
                    sideIcon={<IconMinus />}
                    onClick={() => {
                        closeSidePanel()
                        setIsFloatingMaxExpanded(true)
                    }}
                    tooltip="Minimize to floating Max"
                />
            )}
        </>
    )

    return (
        <>
            {sidePanel && (
                <SidePanelPaneHeader
                    className="transition-all duration-200"
                    onClose={() => {
                        startNewConversation()
                        setIsFloatingMaxExpanded(false)
                    }}
                >
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
                                    className="flex items-center font-semibold mb-0 line-clamp-1 text-sm ml-1"
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
                        {featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG] && (
                            <LemonButton
                                size="small"
                                sideIcon={<IconMinus />}
                                onClick={() => {
                                    closeSidePanel()
                                    setIsFloatingMaxExpanded(true)
                                }}
                                tooltip="Minimize to floating Max"
                            />
                        )}
                    </div>
                </SidePanelPaneHeader>
            )}
            <PageHeader buttons={headerButtons} />
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                {conversationHistoryVisible ? (
                    <ConversationHistory sidePanel={sidePanel} />
                ) : !threadVisible ? (
                    // pb-7 below is intentionally specific - it's chosen so that the bottom-most chat's title
                    // is at the same viewport height as the QuestionInput text that appear after going into a thread.
                    // This makes the transition from one view into another just that bit smoother visually.
                    <div className="@container/max-welcome relative flex flex-col gap-4 px-4 pb-7 grow">
                        {wasUserAutoEnrolled && (
                            <LemonBanner
                                type="info"
                                className="mt-3"
                                hideIcon={false}
                                onClose={() => setWasUserAutoEnrolled(false)}
                            >
                                PostHog AI feature preview{' '}
                                <Link
                                    to={
                                        combineUrl(currentLocation.pathname, currentLocation.search, {
                                            ...currentLocation.hashParams,
                                            panel: `${SidePanelTab.FeaturePreviews}:${FEATURE_FLAGS.ARTIFICIAL_HOG}`,
                                        }).url
                                    }
                                >
                                    activated
                                </Link>
                                !
                            </LemonBanner>
                        )}
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
        </>
    )
})
