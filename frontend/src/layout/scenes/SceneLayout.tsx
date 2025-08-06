import { IconComment, IconInfo, IconX } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label, LabelProps } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import React, { PropsWithChildren, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { SceneConfig } from 'scenes/sceneTypes'
import { SceneHeader } from './SceneHeader'
import './SceneLayout.css'
import { sceneLayoutLogic } from './sceneLayoutLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { SceneTabs } from '~/layout/scenes/SceneTabs'
import { SidePanelDiscussion } from '../navigation-3000/sidepanel/panels/discussion/SidePanelDiscussion'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    layoutConfig?: SceneConfig | null
}

export function ScenePanel({ children }: { children: React.ReactNode }): JSX.Element {
    const { scenePanelElement } = useValues(sceneLayoutLogic)
    const { setScenePanelIsPresent } = useActions(sceneLayoutLogic)
    // HACKY: Show the panel only if this element in in the DOM
    useEffect(() => {
        setScenePanelIsPresent(true)
        return () => {
            setScenePanelIsPresent(false)
        }
    }, [setScenePanelIsPresent])

    return (
        <>
            {children &&
                scenePanelElement &&
                createPortal(<div className="flex flex-col gap-px pt-4">{children}</div>, scenePanelElement)}
        </>
    )
}

export function ScenePanelDivider(): JSX.Element {
    return <LemonDivider className="-mx-2 my-2 w-[calc(100%+1rem)]" />
}

// Should be first!
export const ScenePanelCommonActions = ({
    children,
    isFirst = true,
}: {
    children: React.ReactNode
    isFirst?: boolean
}): JSX.Element => {
    return (
        <>
            <div className={cn('flex flex-col gap-2', { '-mt-2': isFirst })}>{children}</div>
            <ScenePanelDivider />
        </>
    )
}

// Should be second!
export function ScenePanelMetaInfo({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="pl-1 pb-1 flex flex-col gap-2 -ml-1">{children}</div>
}

// Should be third!
export function ScenePanelActions({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 pl-1 -ml-1">
            <Label intent="menu" className="mx-2">
                Actions
            </Label>
            <div className="flex flex-col gap-px -ml-1 pl-1">{children}</div>
        </div>
    )
}

export function ScenePanelLabel({ children, title, ...props }: PropsWithChildren<LabelProps>): JSX.Element {
    return (
        <div className="flex flex-col gap-0">
            <Label intent="menu" {...props} className="mx-button-padding-x">
                {title}
            </Label>
            {children}
        </div>
    )
}

export function SceneLayout({ children, className, layoutConfig }: SceneLayoutProps): JSX.Element {
    const {
        registerScenePanelElement,
        setScenePanelOpen,
        setSceneContainerRef,
        setForceScenePanelClosedWhenRelative,
        setActiveTab,
    } = useActions(sceneLayoutLogic)
    const { scenePanelIsPresent, scenePanelOpen, useSceneTabs, scenePanelIsRelative, activeTab } =
        useValues(sceneLayoutLogic)
    const sceneLayoutContainer = useRef<HTMLDivElement>(null)
    const [outerRight, setOuterRight] = useState<number>(0)

    useOnMountEffect(() => {
        const updateOuterRight = (): void => {
            if (sceneLayoutContainer.current) {
                setOuterRight(sceneLayoutContainer.current.getBoundingClientRect().right)
            }
        }

        // Update on mount and when window resizes
        updateOuterRight()
        window.addEventListener('resize', updateOuterRight)

        return () => {
            window.removeEventListener('resize', updateOuterRight)
        }
    })

    // Set container ref so we can measure the width of the scene layout in logic
    useEffect(() => {
        if (sceneLayoutContainer.current) {
            setSceneContainerRef(sceneLayoutContainer)
        }
    }, [sceneLayoutContainer, setSceneContainerRef])

    return (
        <div
            className={cn('scene-layout', className)}
            ref={sceneLayoutContainer}
            style={
                {
                    '--scene-layout-outer-right': outerRight + 'px',
                } as React.CSSProperties
            }
        >
            <div
                className={cn('relative min-h-screen', {
                    block: layoutConfig?.layout === 'app-raw-no-header',
                })}
            >
                <div
                    className={cn('relative min-h-screen', {
                        'w-[calc(100%-var(--scene-layout-panel-width))]':
                            scenePanelIsPresent && scenePanelIsRelative && scenePanelOpen,
                    })}
                >
                    {useSceneTabs ? <SceneTabs /> : null}
                    {layoutConfig?.layout !== 'app-raw-no-header' && (
                        <SceneHeader className="row-span-1 col-span-1 min-w-0" />
                    )}

                    <div
                        className={cn(
                            'flex-1 flex flex-col p-4 pb-16 w-full order-1 row-span-1 col-span-1 col-start-1 relative min-w-0',
                            {
                                'p-0 h-screen': layoutConfig?.layout === 'app-raw-no-header',
                                'p-0 h-[calc(100vh-var(--scene-layout-header-height))]':
                                    layoutConfig?.layout === 'app-raw',
                            }
                        )}
                    >
                        {children}
                    </div>
                </div>

                {scenePanelIsPresent && (
                    <>
                        <div
                            className={cn(
                                'scene-layout__content-panel order-2 bg-surface-secondary flex flex-col overflow-hidden row-span-2 col-span-2 row-start-1 col-start-2 top-0 h-screen min-w-0 fixed left-[calc(var(--scene-layout-outer-right)-var(--scene-layout-panel-width)-1px)]',
                                {
                                    hidden: !scenePanelOpen,
                                }
                            )}
                        >
                            <div className="h-[var(--scene-layout-header-height)] flex items-center justify-between gap-2 -mx-2 px-4 py-1 border-b border-primary shrink-0">
                                <div className="w-5" />

                                <div className="flex gap-0.5">
                                    <ButtonPrimitive
                                        iconOnly
                                        onClick={() => setActiveTab('info')}
                                        tooltip="Info"
                                        aria-label="Info"
                                        active={activeTab === 'info'}
                                    >
                                        <IconInfo className="size-4" />
                                    </ButtonPrimitive>
                                    <ButtonPrimitive
                                        iconOnly
                                        onClick={() => setActiveTab('discussions')}
                                        tooltip="Discussions"
                                        aria-label="Discussions"
                                        active={activeTab === 'discussions'}
                                    >
                                        <IconComment className="size-4" />
                                    </ButtonPrimitive>
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
                                            scenePanelIsRelative
                                                ? 'Force close info panel'
                                                : scenePanelOpen
                                                  ? 'Close info panel'
                                                  : 'Open info panel'
                                        }
                                        aria-label={
                                            scenePanelIsRelative
                                                ? 'Force close info panel'
                                                : scenePanelOpen
                                                  ? 'Close info panel'
                                                  : 'Open info panel'
                                        }
                                    >
                                        <IconX className="size-4" />
                                    </ButtonPrimitive>
                                )}
                            </div>
                            {activeTab === 'info' ? (
                                <ScrollableShadows
                                    direction="vertical"
                                    className="h-full flex-1"
                                    innerClassName="px-2 pb-4 bg-primary"
                                    styledScrollbars
                                >
                                    <div ref={registerScenePanelElement} />
                                </ScrollableShadows>
                            ) : activeTab === 'discussions' ? (
                                <SidePanelDiscussion showHeader={false} />
                            ) : null}
                        </div>

                        {scenePanelOpen && !scenePanelIsRelative && (
                            <div
                                onClick={() => {
                                    setScenePanelOpen(false)
                                }}
                                aria-hidden="true"
                                className="z-[var(--z-top-navigation-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-100"
                            />
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
