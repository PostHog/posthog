import {
    IconArrowLeft,
    IconChevronLeft,
    IconClockRewind,
    IconExternal,
    IconGear,
    IconPlus,
    IconSidePanel,
} from '@posthog/icons'
import { LemonBanner, Link } from '@posthog/lemon-ui'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'
import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { AnimatedBackButton } from './components/AnimatedBackButton'
import { ConversationHistory } from './ConversationHistory'
import { HistoryPreview } from './HistoryPreview'
import { Intro } from './Intro'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { QuestionInput } from './QuestionInput'
import { QuestionSuggestions } from './QuestionSuggestions'
import { Thread } from './Thread'

export const scene: SceneExport = {
    component: Max,
    logic: maxGlobalLogic,
}

export function Max(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { closeSidePanel } = useActions(sidePanelLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    if (sidePanelOpen && selectedTab === SidePanelTab.Max) {
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

    return <MaxInstance />
}

export interface MaxInstanceProps {
    sidePanel?: boolean
}

export function MaxInstance({ sidePanel }: MaxInstanceProps): JSX.Element {
    const { threadVisible, conversationHistoryVisible, chatTitle, backButtonDisabled } = useValues(maxLogic)
    const { startNewConversation, toggleConversationHistory, goBack } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
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
    }, [])

    const headerButtons = (
        <>
            <LemonButton
                size="small"
                icon={<IconPlus />}
                onClick={() => startNewConversation()}
                tooltip="Start a new chat"
                tooltipPlacement="bottom"
            />
            <LemonButton
                size="small"
                sideIcon={<IconClockRewind />}
                onClick={() => toggleConversationHistory()}
                tooltip="Open chat history"
                tooltipPlacement="bottom"
            />
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconGear />}
                onClick={() => {
                    openSettingsPanel({ settingId: 'core-memory' })
                    setTimeout(() => document.getElementById('product-description-textarea')?.focus(), 1)
                }}
            >
                Settings
            </LemonButton>
        </>
    )

    return (
        <>
            {sidePanel && (
                <SidePanelPaneHeader className="transition-all duration-200">
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
                                    className="font-semibold mb-0 line-clamp-1 text-sm ml-1"
                                    title={chatTitle !== 'Max' ? chatTitle : undefined}
                                >
                                    {chatTitle}
                                </h3>
                            ) : (
                                <LemonSkeleton className="h-5 w-48 ml-1" />
                            )}
                        </div>
                        <LemonButton
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => startNewConversation()}
                            tooltip="Start a new chat"
                            tooltipPlacement="bottom"
                        />
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
            <PageHeader delimited buttons={headerButtons} />
            {conversationHistoryVisible ? (
                <ConversationHistory sidePanel={sidePanel} />
            ) : !threadVisible ? (
                // pb-7 below is intentionally specific - it's chosen so that the bottom-most chat's title
                // is at the same viewport height as the QuestionInput text that appear after going into a thread.
                // This makes the transition from one view into another just that bit smoother visually.
                <div className="@container/max-welcome relative gap-6 px-4 pb-7 grow grid grid-rows-2">
                    <div className="flex flex-col justify-end">
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
                        <div className="items-center justify-center flex flex-col gap-3">
                            <Intro />
                            <QuestionInput />
                        </div>
                    </div>
                    <div className="flex flex-col justify-between w-[min(44rem,100%)] items-center justify-self-center gap-4">
                        <QuestionSuggestions />
                        <HistoryPreview sidePanel={sidePanel} />
                    </div>
                </div>
            ) : (
                <>
                    <Thread />
                    <QuestionInput isFloating />
                </>
            )}
        </>
    )
}
