import { IconInfo, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { SceneConfig } from 'scenes/sceneTypes'
import { SceneHeader } from './SceneHeader'
import './SceneLayout.css'
import { sceneLayoutLogic } from './sceneLayoutLogic'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    layoutConfig?: SceneConfig | null
}

export function SceneLayoutPanelInfo({ children }: { children: React.ReactNode }): JSX.Element {
    const { fileActionsContainer } = useValues(sceneLayoutLogic)
    const { setPanelInfoActive } = useActions(sceneLayoutLogic)
    // HACKY: Show the panel only if this element in in the DOM
    useEffect(() => {
        setPanelInfoActive(true)
        return () => {
            setPanelInfoActive(false)
        }
    }, [setPanelInfoActive])

    return (
        <>
            {children &&
                fileActionsContainer &&
                createPortal(<div className="flex flex-col gap-px">{children}</div>, fileActionsContainer)}
        </>
    )
}

export function SceneLayout({ children, className, layoutConfig }: SceneLayoutProps): JSX.Element {
    const { setFileActionsContainer, setPanelInfoOpen, setShowPanelOverlay } = useActions(sceneLayoutLogic)
    const { panelInfoActive, showPanelOverlay, panelInfoOpen } = useValues(sceneLayoutLogic)
    const sceneLayoutContainer = useRef<HTMLDivElement>(null)
    const { mobileLayout } = useValues(navigation3000Logic)

    useEffect(() => {
        if (sceneLayoutContainer.current) {
            const resizeObserver = new ResizeObserver((entries) => {
                for (const entry of entries) {
                    if (entry.contentRect.width >= 1300) {
                        setShowPanelOverlay(false)
                    } else {
                        setShowPanelOverlay(true)
                    }
                }
            })

            resizeObserver.observe(sceneLayoutContainer.current)

            return () => {
                resizeObserver.disconnect()
            }
        }
    }, [setPanelInfoOpen])

    return (
        <div
            className={cn('scene-layout flex-1 flex flex-col', className, {
                'scene-layout--has-panel-overlay': panelInfoActive,
            })}
            ref={sceneLayoutContainer}
        >
            <div className="scene-layout__content">
                <div className="flex flex-col flex-1">
                    {layoutConfig?.layout !== 'app-raw-no-header' && <SceneHeader />}

                    <div
                        className={cn('flex-1 flex flex-col p-4 w-full order-1', {
                            'p-0': layoutConfig?.layout === 'app-raw-no-header',
                        })}
                    >
                        {children}
                    </div>
                </div>

                {panelInfoActive && (
                    <>
                        <div
                            className={cn('scene-layout__content-panel order-2 bg-surface-primary flex flex-col', {
                                hidden: !panelInfoOpen && showPanelOverlay,
                                'right-0': mobileLayout,
                                'right-[3rem]': !mobileLayout,
                            })}
                        >
                            <div className="h-[var(--scene-header-height)] flex items-center justify-between gap-2 -mx-2 px-4 py-1 border-b border-primary shrink-0">
                                <div className="flex items-center gap-2">
                                    <IconInfo className="size-6 text-tertiary" />
                                    <h4 className="text-base font-medium text-primary m-0">Info</h4>
                                </div>

                                {showPanelOverlay && panelInfoOpen && (
                                    <ButtonPrimitive iconOnly onClick={() => setPanelInfoOpen(false)}>
                                        <IconX className="size-4" />
                                    </ButtonPrimitive>
                                )}
                            </div>
                            <ScrollableShadows
                                direction="vertical"
                                className="h-full flex-1"
                                innerClassName="px-2 pb-4"
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
                        {panelInfoOpen && showPanelOverlay && (
                            <div
                                onClick={() => {
                                    setPanelInfoOpen(false)
                                }}
                                className="z-[var(--z-top-navigation-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-100"
                            />
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
