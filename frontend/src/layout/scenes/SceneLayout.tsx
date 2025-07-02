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
import { Label } from 'lib/ui/Label/Label'
import { LemonDivider } from '@posthog/lemon-ui'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    layoutConfig?: SceneConfig | null
}

export function ScenePanel({ children }: { children: React.ReactNode }): JSX.Element {
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

export function ScenePanelDivider(): JSX.Element {
    return <LemonDivider className="-mx-2 my-2 w-[calc(100%+1rem)]" />
}

export function ScenePanelMetaInfo({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="px-1 pt-4 flex flex-col gap-2">{children}</div>
}

export function ScenePanelActions({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Label intent="menu" className="px-1">
                Actions
            </Label>
            <div className="flex flex-col gap-px">{children}</div>
        </div>
    )
}

export function SceneLayout({ children, className, layoutConfig }: SceneLayoutProps): JSX.Element {
    const { setFileActionsContainer, setPanelInfoOpen, setShowPanelOverlay } = useActions(sceneLayoutLogic)
    const { panelInfoActive, showPanelOverlay, panelInfoOpen } = useValues(sceneLayoutLogic)
    const sceneLayoutContainer = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (sceneLayoutContainer.current) {
            const resizeObserver = new ResizeObserver((entries) => {
                for (const entry of entries) {
                    if (entry.contentRect.width >= 1300) {
                        setShowPanelOverlay(false)
                        setPanelInfoOpen(true)
                    } else {
                        setShowPanelOverlay(true)
                        setPanelInfoOpen(false)
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
            className={cn('scene-layout flex-1 flex flex-col', className)}
            ref={sceneLayoutContainer}
            style={
                {
                    '--scene-layout-outer-right': sceneLayoutContainer.current?.getBoundingClientRect().right + 'px',
                } as React.CSSProperties
            }
        >
            <div
                className={cn('grid grid-rows-[42px_1fr] grid-cols-[1fr_auto] relative min-h-screen', {
                    block: layoutConfig?.layout === 'app-raw-no-header',
                })}
            >
                {layoutConfig?.layout !== 'app-raw-no-header' && <SceneHeader className="row-span-1 col-span-1" />}

                {panelInfoActive && (
                    <>
                        <div
                            className={cn(
                                'scene-layout__content-panel order-2 bg-primary flex flex-col overflow-hidden row-span-2 col-span-2 row-start-1 col-start-2 sticky top-0 h-screen',
                                {
                                    hidden: !panelInfoOpen,
                                    // When it's a modal, we do fixed positioning to keep it floating and not scrolling relative to the page
                                    'fixed left-[calc(var(--scene-layout-outer-right)-var(--scene-layout-panel-width)-1px)]':
                                        showPanelOverlay,
                                }
                            )}
                        >
                            <div className="h-[var(--scene-layout-header-height)] flex items-center justify-between gap-2 -mx-2 px-4 py-1 border-b border-primary shrink-0">
                                <div className="flex items-center gap-2">
                                    <IconInfo className="size-5 text-tertiary" />
                                    <h4 className="text-base font-medium text-primary m-0">Info</h4>
                                </div>

                                {panelInfoOpen && (
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
                <div
                    className={cn(
                        'flex-1 flex flex-col p-4 w-full order-1 row-span-1 col-span-1 col-start-1 relative',
                        {
                            'p-0 h-screen': layoutConfig?.layout === 'app-raw-no-header',
                        }
                    )}
                >
                    {children}
                </div>
            </div>
        </div>
    )
}
