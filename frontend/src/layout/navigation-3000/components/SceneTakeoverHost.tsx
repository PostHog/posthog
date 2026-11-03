import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { cn } from 'lib/utils/css-classes'

import { sceneLayoutLogic } from '../../scenes/sceneLayoutLogic'

/** Portal target for fullscreen-in-scene surfaces such as the email editor. */
export function SceneTakeoverHost({ sidePanelOverlapsMain }: { sidePanelOverlapsMain: boolean }): JSX.Element {
    const { registerSceneTakeoverElement } = useActions(sceneLayoutLogic)
    const { sceneTakeoverActive } = useValues(sceneLayoutLogic)

    // Nothing else overrides this registration, so the ref's null call on unmount cleans up.
    const takeoverCallbackRef = useCallback(
        (node: HTMLDivElement | null) => registerSceneTakeoverElement(node),
        [registerSceneTakeoverElement]
    )

    return (
        <div
            ref={takeoverCallbackRef}
            tabIndex={-1}
            className={cn('absolute inset-0 z-50 bg-[var(--scene-layout-background)] flex flex-col outline-none', {
                hidden: !sceneTakeoverActive,
                'lg:max-w-[calc(100%-var(--side-panel-width))]': sidePanelOverlapsMain,
            })}
        />
    )
}
