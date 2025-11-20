import { useActions, useValues } from 'kea'

import { IconListCheck, IconX } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { sceneLayoutLogic } from '../sceneLayoutLogic'

export function ScenePanelLayout(): JSX.Element {
    const { scenePanelOpen, scenePanelIsRelative, forceScenePanelClosedWhenRelative } = useValues(sceneLayoutLogic)
    const { setForceScenePanelClosedWhenRelative, setScenePanelOpen, registerScenePanelElement } =
        useActions(sceneLayoutLogic)
    const { isLayoutPanelVisible, isLayoutPanelPinned } = useValues(panelLayoutLogic)

    if (!scenePanelIsRelative) {
        return <div ref={registerScenePanelElement} />
    }

    return (
        <>
            <div
                className={cn(
                    'scene-layout__content-panel fixed left-[calc(var(--scene-layout-rect-right)-var(--scene-layout-panel-width)+var(--scene-layout-scrollbar-width))] bg-surface-secondary flex flex-col overflow-hidden h-[calc(var(--scene-layout-rect-height)-var(--scene-layout-header-height))] top-[var(--scene-layout-header-height)] min-w-0',
                    {
                        hidden: !scenePanelOpen,
                        'col-start-2 col-span-1 row-start-1 row-span-2':
                            scenePanelIsRelative && !forceScenePanelClosedWhenRelative,
                        'z-1': isLayoutPanelVisible && !isLayoutPanelPinned,
                    }
                )}
            >
                <div className="h-[var(--scene-layout-header-height)] flex items-center justify-between gap-2 -mx-2 px-4 py-1 border-b border-primary shrink-0">
                    <div className="flex items-center gap-2">
                        <IconListCheck className="size-5 text-tertiary" />
                        <h4 className="text-base font-medium text-primary m-0">Info & actions</h4>
                    </div>

                    {scenePanelOpen && (
                        <ButtonPrimitive
                            iconOnly
                            onClick={() =>
                                scenePanelIsRelative
                                    ? setForceScenePanelClosedWhenRelative(true)
                                    : setScenePanelOpen(false)
                            }
                            tooltip={
                                !scenePanelOpen
                                    ? 'Open Info & actions panel'
                                    : scenePanelIsRelative
                                      ? 'Force close Info & actions panel'
                                      : 'Close Info & actions panel'
                            }
                            aria-label={
                                !scenePanelOpen
                                    ? 'Open Info & actions panel'
                                    : scenePanelIsRelative
                                      ? 'Force close Info & actions panel'
                                      : 'Close Info & actions panel'
                            }
                            data-attr="info-actions-panel"
                        >
                            <IconX className="size-4" />
                        </ButtonPrimitive>
                    )}
                </div>
                <ScrollableShadows
                    direction="vertical"
                    className="h-full flex-1"
                    innerClassName="px-2 py-2 bg-primary"
                    styledScrollbars
                >
                    <div ref={registerScenePanelElement} />
                </ScrollableShadows>
            </div>
        </>
    )
}
