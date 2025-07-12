import { BindLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'

import { ExpandedFloatingMax } from './components/ExpandedFloatingMax'
import { CollapsedFloatingMax } from './components/CollapsedFloatingMax'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import './MaxFloatingInput.scss'
import { useFloatingMaxPosition } from './utils/floatingMaxPositioning'

export function MaxFloatingInput(): JSX.Element | null {
    const { threadLogicKey, conversation } = useValues(maxLogic)

    const { isFloatingMaxExpanded, floatingMaxDragState, showFloatingMax } = useValues(maxGlobalLogic)
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

    if (!showFloatingMax) {
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
