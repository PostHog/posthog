import { IconOpenSidebar, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useEffect } from 'react'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { BaseQuestionInput } from './components/BaseQuestionInput'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'

interface QuestionInputWithInteractionTrackingProps {
    placeholder?: string
}

const QuestionInputWithInteractionTracking = React.forwardRef<
    HTMLDivElement,
    QuestionInputWithInteractionTrackingProps
>(function QuestionInputWithInteractionTracking({ placeholder }, ref) {
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <BaseQuestionInput
            ref={ref}
            isFloating={true}
            placeholder={placeholder}
            contextDisplaySize="small"
            topActions={
                <>
                    <Tooltip title="Expand to side panel" placement="top" delayMs={0}>
                        <LemonButton
                            size="xxsmall"
                            icon={<IconOpenSidebar className="size-3" />}
                            type="tertiary"
                            onClick={() => {
                                openSidePanel(SidePanelTab.Max)
                                setIsFloatingMaxExpanded(false)
                            }}
                        />
                    </Tooltip>
                    <Tooltip title="Close" placement="top" delayMs={0}>
                        <LemonButton
                            size="xxsmall"
                            icon={<IconX className="size-3" />}
                            type="tertiary"
                            onClick={() => setIsFloatingMaxExpanded(false)}
                        />
                    </Tooltip>
                </>
            }
            containerClassName="px-1 sticky bottom-0 z-10 w-full max-w-[45rem] self-center"
        />
    )
})

function MaxFloatingInputWithLogic(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelLogic)
    const { activeStreamingThreads } = useValues(maxLogic)

    // Watch for when a new conversation starts and open the sidebar
    useEffect(() => {
        if (activeStreamingThreads > 0) {
            openSidePanel(SidePanelTab.Max)
        }
    }, [activeStreamingThreads, openSidePanel])

    return <QuestionInputWithInteractionTracking placeholder="Ask Max AI" />
}

export function MaxFloatingInput(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { isFloatingMaxExpanded } = useValues(maxGlobalLogic)

    const { threadLogicKey, conversation } = useValues(maxLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] || !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) {
        return null
    }

    if (!isFloatingMaxExpanded || (sidePanelOpen && selectedTab === SidePanelTab.Max)) {
        return null
    }

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        // `right:` gets 1px removed to account for border
        <div className="fixed bottom-0 z-[var(--z-hedgehog-buddy)] max-w-sm w-80 transition-all md:right-[calc(3rem-1px)] right-[calc(1rem-1px)]">
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputWithLogic />
            </BindLogic>
        </div>
    )
}
