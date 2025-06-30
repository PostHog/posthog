import { useActions, useValues } from 'kea'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'
import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { SceneConfig } from 'scenes/sceneTypes'
import { SceneHeader } from './SceneHeader'
import './SceneLayout.css'
import { sceneLayoutLogic } from './sceneLayoutLogic'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    layoutConfig?: SceneConfig | null
}

export function SceneLayoutPanelInfo({ children }: { children: React.ReactNode }): JSX.Element {
    const { fileActionsContainer } = useValues(sceneLayoutLogic)
    const { setPanelInfoActive, setPanelInfoOpen } = useActions(sceneLayoutLogic)

    // HACKY: Show the panel only if this element in in the DOM
    useEffect(() => {
        setPanelInfoActive(true)
        setPanelInfoOpen(false)
        return () => {
            setPanelInfoActive(false)
            setPanelInfoOpen(false)
        }
    }, [setPanelInfoActive, setPanelInfoOpen])

    return (
        <>
            {children &&
                fileActionsContainer &&
                createPortal(<div className="flex flex-col gap-px">{children}</div>, fileActionsContainer)}
        </>
    )
}

export function SceneLayout({ children, className, layoutConfig }: SceneLayoutProps): JSX.Element {
    const { setFileActionsContainer, setPanelInfoOpen } = useActions(sceneLayoutLogic)
    const { panelInfoActive, panelInfoOpen } = useValues(sceneLayoutLogic)
    const sceneLayoutContainer = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (sceneLayoutContainer.current) {
            const resizeObserver = new ResizeObserver((entries) => {
                for (const entry of entries) {
                    if (entry.contentRect.width > 1300) {
                        setPanelInfoOpen(true)
                    }
                }
            })

            resizeObserver.observe(sceneLayoutContainer.current)

            return () => {
                setPanelInfoOpen(false)
                resizeObserver.disconnect()
            }
        }
    }, [setPanelInfoOpen])

    return (
        <div className={cn('scene-layout flex-1 flex flex-col h-full', className)} ref={sceneLayoutContainer}>
            {layoutConfig?.layout !== 'app-raw-no-header' && <SceneHeader />}
            <div
                className={cn('scene-layout__content', {
                    'scene-layout__content--has-panel': panelInfoActive && panelInfoOpen,
                })}
            >
                {panelInfoActive && panelInfoOpen && (
                    <>
                        <div className={cn('scene-layout__content-panel order-2 right-0')}>
                            <ScrollableShadows
                                direction="vertical"
                                className="h-full"
                                innerClassName="p-2 bg-surface-primary rounded-sm border border-primary"
                            >
                                <div ref={setFileActionsContainer} />
                            </ScrollableShadows>
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
ettings
                            </TabsPrimitiveContent>
                        </TabsPrimitive> */}
                        </div>
                        <div
                            onClick={() => {
                                setPanelInfoOpen(false)
                            }}
                            className="z-[var(--z-top-navigation-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-100"
                        />
                    </>
                )}
                <div
                    className={cn('flex-1 flex flex-col p-4 w-full order-1', {
                        'p-0': layoutConfig?.layout === 'app-raw-no-header',
                    })}
                >
                    {children}
                </div>
            </div>
        </div>
    )
}
