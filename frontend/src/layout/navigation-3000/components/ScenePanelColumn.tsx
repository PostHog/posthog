import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '../../panel-layout/panelLayoutLogic'
import { SceneTitlePanelButton } from '../../scenes/components/SceneTitlePanelButton'
import { sceneLayoutLogic } from '../../scenes/sceneLayoutLogic'
import { sidePanelStateLogic } from '../sidepanel/sidePanelStateLogic'

export function ScenePanelColumn(): JSX.Element | null {
    const { scenePanelIsPresent, scenePanelOpenManual } = useValues(sceneLayoutLogic)
    const { registerScenePanelElement } = useActions(sceneLayoutLogic)
    const { isLayoutPanelVisible } = useValues(panelLayoutLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

    const inlinePanelRef = useRef<HTMLDivElement | null>(null)
    const inlinePanelCallbackRef = useCallback(
        (node: HTMLDivElement | null) => {
            inlinePanelRef.current = node
            registerScenePanelElement(node)
        },
        [registerScenePanelElement]
    )

    // SidePanelInfo clears the registration while open. Register this panel again when the side panel closes.
    useEffect(() => {
        if (!sidePanelOpen && inlinePanelRef.current) {
            registerScenePanelElement(inlinePanelRef.current)
        }
    }, [sidePanelOpen, registerScenePanelElement])

    // Clear the detached panel on unmount. A separate effect avoids blanking the portal on every side panel toggle.
    useEffect(() => {
        return () => {
            registerScenePanelElement(null)
        }
    }, [registerScenePanelElement])

    if (!scenePanelIsPresent) {
        return null
    }

    return (
        <div
            className={cn(
                'scene-layout__content-panel starting:w-0 bg-surface-secondary flex flex-col overflow-hidden h-full min-w-0',
                'absolute right-0 top-0 @[1200px]/main-content-container:relative @[1200px]/main-content-container:right-auto @[1200px]/main-content-container:top-auto',
                {
                    hidden: !scenePanelOpenManual,
                    'z-1': isLayoutPanelVisible,
                }
            )}
        >
            <div className="h-[50px] flex items-center justify-end gap-2 -mx-2 px-4 py-2 border-b border-primary shrink-0">
                <SceneTitlePanelButton />
            </div>
            <ScrollableShadows
                direction="vertical"
                className="grow flex-1"
                innerClassName="px-2 py-2 bg-primary"
                styledScrollbars
            >
                <div ref={inlinePanelCallbackRef} />
            </ScrollableShadows>
        </div>
    )
}
