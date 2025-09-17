import './MaxFloatingInput.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { CollapsedFloatingMax } from './components/CollapsedFloatingMax'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from './maxThreadLogic'
import { useFloatingMaxPosition } from './utils/floatingMaxPositioning'

export function MaxFloatingInput(): JSX.Element | null {
    const { threadLogicKey, conversation } = useValues(maxLogic)
    const { floatingMaxDragState, showFloatingMax } = useValues(maxGlobalLogic)
    const { setFloatingMaxPosition } = useActions(maxGlobalLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const { floatingMaxPositionStyle } = useFloatingMaxPosition()

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
                              'border backdrop-blur-sm bg-[var(--glass-bg-3000)] mb-2'
                          )
                }
                style={
                    floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                        ? {
                              position: 'fixed',
                              zIndex: 1000,
                              borderRadius: '50%',
                              marginRight: '1rem',
                          }
                        : floatingMaxPositionStyle
                }
            >
                <CollapsedFloatingMax
                    onExpand={() => openSidePanel(SidePanelTab.Max)}
                    onPositionChange={setFloatingMaxPosition}
                />
            </div>
        </BindLogic>
    )
}
