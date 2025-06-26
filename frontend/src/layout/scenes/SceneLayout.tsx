import { IconGear, IconInfo } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TabsPrimitive, TabsPrimitiveContent, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import React from 'react'
import { createPortal } from 'react-dom'
import { SceneHeader } from './SceneHeader'
import { sceneLayoutLogic } from './sceneLayoutLogic'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    showHeader?: boolean
}

export function SceneLayoutPanelInfo({children}: {children: React.ReactNode}): JSX.Element {
    const { fileActionsContainer } = useValues(sceneLayoutLogic)

    return (
        <>
            {/* <div className="text-sm text-secondary">
                Info
            </div>
            <div>
                {fileActions.map((action) => (
                    <ButtonPrimitive key={action.id} onClick={action.onClick}>
                        {action.title}
                    </ButtonPrimitive>
                ))}
            </div> */}
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

export function SceneLayout({ children, className, showHeader }: SceneLayoutProps): JSX.Element {
    const { setFileActionsContainer } = useActions(sceneLayoutLogic)

    return (
        <div className={cn('flex-1 flex flex-col', className)}>
            {showHeader && <SceneHeader />}
            <div className="grid grid-cols-[calc(100%-200px)_200px]">
                <div className="flex-1 flex flex-col p-4 w-full">
                    {children}
                </div>
                <div className="border-l border-primary w-[200px]">
                    <TabsPrimitive defaultValue="info">
                        <div className="flex justify-between items-center border-b border-primary">
                            <TabsPrimitiveList>
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
                            {/* <div ref={editRef}/> */}
                            settings
                        </TabsPrimitiveContent>
                    </TabsPrimitive>
                </div>
            </div>
        </div>
    )
}
