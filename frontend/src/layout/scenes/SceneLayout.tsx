import { IconGear, IconInfo } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TabsPrimitive, TabsPrimitiveContent, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { SceneHeader } from './SceneHeader'
import { sceneLayoutLogic } from './sceneLayoutLogic'
import { SceneConfig } from 'scenes/sceneTypes'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    layoutConfig?: SceneConfig | null
}

export function SceneLayoutPanelInfo({children}: {children: React.ReactNode}): JSX.Element {
    const { fileActionsContainer } = useValues(sceneLayoutLogic)
    const { setPanelInfoActive } = useActions(sceneLayoutLogic)

    useEffect(() => {
        setPanelInfoActive(true)
        return () => setPanelInfoActive(false)
    }, [setPanelInfoActive])

    return (
        <>
            {children &&
                fileActionsContainer &&
                createPortal(
                    <div className="flex flex-col gap-px">
                        {children}
                    </div>,
                    fileActionsContainer
                )}
        </>
    )
}

export function SceneLayout({ children, className, layoutConfig }: SceneLayoutProps): JSX.Element {
    const { setFileActionsContainer } = useActions(sceneLayoutLogic)
    const { panelInfoActive } = useValues(sceneLayoutLogic)

    return (
        <div className={cn('flex-1 flex flex-col', className)}>
            {layoutConfig?.layout !== 'app-raw-no-header' && <SceneHeader />}
            <div className={cn('grid', {
                'grid-cols-[calc(100%-200px)_200px]': panelInfoActive,
                'grid-cols-1': !panelInfoActive,
            })}>
                <div className={cn('flex-1 flex flex-col p-4 w-full', {
                    'p-0': layoutConfig?.layout === 'app-raw-no-header'
                })}>
                    {children}
                </div>
                {panelInfoActive && (
                    <div className="border-l border-primary w-[200px] p-1">
                        <div ref={setFileActionsContainer}/>
                        {/* <TabsPrimitive defaultValue="info">
                            <div className="flex justify-between items-center border-b border-primary">
                                <TabsPrimitiveList className="px-2">
                                    <TabsPrimitiveTrigger value="info" asChild>
                                        <ButtonPrimitive size="sm">
                                            <IconInfo />
                                            Info
                                        </ButtonPrimitive>
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger value="settings" asChild>
                                        <ButtonPrimitive size="sm">
                                            <IconGear />
                                            Settings
                                        </ButtonPrimitive>
                                    </TabsPrimitiveTrigger>
                                </TabsPrimitiveList>
                            </div>
                            <TabsPrimitiveContent value="info" className="p-1">
                                <div ref={setFileActionsContainer}/>
                            </TabsPrimitiveContent>
                            <TabsPrimitiveContent value="settings" className="p-1">
                                settings
                            </TabsPrimitiveContent>
                        </TabsPrimitive> */}
                    </div>
                )}
            </div>
        </div>
    )
}
