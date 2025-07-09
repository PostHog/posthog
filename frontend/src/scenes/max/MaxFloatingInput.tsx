import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import clsx from 'clsx'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'

import { ExpandedFloatingMax } from './components/ExpandedFloatingMax'
import { CollapsedFloatingMax } from './components/CollapsedFloatingMax'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import './MaxFloatingInput.scss'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { SidePanelTab } from '~/types'
import { useFloatingMaxPosition } from './utils/floatingMaxPositioning'

export function MaxFloatingInput(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { scene, sceneConfig } = useValues(sceneLogic)
    const { threadLogicKey, conversation } = useValues(maxLogic)

    const { isFloatingMaxExpanded, floatingMaxDragState } = useValues(maxGlobalLogic)
    const { setFloatingMaxPosition } = useActions(maxGlobalLogic)
    const { floatingMaxPositionStyle } = useFloatingMaxPosition()

    const { setActiveGroup } = useActions(maxLogic)
    const { setIsFloatingMaxExpanded, setShowFloatingMaxSuggestions } = useActions(maxGlobalLogic)
    const { startNewConversation } = useActions(maxLogic)

    const handleExpand = (): void => {
        setIsFloatingMaxExpanded(true)
    }

    const handleDismiss = (): void => {
        setActiveGroup(null)
        setShowFloatingMaxSuggestions(false)
    }

    const handleCollapse = (): void => {
        setActiveGroup(null)
        setShowFloatingMaxSuggestions(false)
        setIsFloatingMaxExpanded(false)
        startNewConversation()
    }

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] || !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) {
        return null
    }

    // Hide floating Max IF:
    if (
        (scene === Scene.Max && !isFloatingMaxExpanded) || // In the full Max scene, and Max is not intentionally in floating mode (i.e. expanded)
        (sidePanelOpen && selectedTab === SidePanelTab.Max) // The Max side panel is open
    ) {
        return null
    }

    if (sceneConfig?.layout === 'plain') {
        return null
    }

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        <BindLogic logic={maxThreadLogic} props={threadProps}>
            <div
                data-attr="floating-max-container"
                className={
                    floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                        ? ''
                        : clsx(
                              'fixed bottom-0 z-[var(--z-hedgehog-buddy)] max-w-sm',
                              'border backdrop-blur-sm bg-[var(--glass-bg-3000)] mb-2',
                              isFloatingMaxExpanded ? 'rounded-lg w-80' : 'rounded-full'
                          )
                }
                style={
                    floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                        ? {
                              position: 'fixed',
                              zIndex: 1000,
                              borderRadius: isFloatingMaxExpanded ? '8px' : '50%',
                              width: isFloatingMaxExpanded ? '20rem' : undefined,
                              marginRight: isFloatingMaxExpanded ? undefined : '1rem',
                          }
                        : floatingMaxPositionStyle
                }
            >
                {isFloatingMaxExpanded ? (
                    <ExpandedFloatingMax onCollapse={handleCollapse} onDismiss={handleDismiss} />
                ) : (
                    <CollapsedFloatingMax onExpand={handleExpand} onPositionChange={setFloatingMaxPosition} />
                )}
            </div>
        </BindLogic>
    )
}
