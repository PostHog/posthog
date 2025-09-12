import './SceneLayout.css'

import { useActions, useValues } from 'kea'
import React, { PropsWithChildren, useEffect } from 'react'
import { createPortal } from 'react-dom'

import { IconListCheck, IconX } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label, LabelProps } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'

import { SceneTabs } from './SceneTabs'
import { sceneLayoutLogic } from './sceneLayoutLogic'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    sceneConfig?: SceneConfig | null
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
                createPortal(<div className="flex flex-col gap-px">{children}</div>, scenePanelElement)}
        </>
    )
}

export function ScenePanelDivider({ className }: { className?: string }): JSX.Element {
    return <LemonDivider className={cn('-mx-2 my-2 w-[calc(100%+1rem)]', className)} />
}

// Should be first!
export const ScenePanelCommonActions = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return (
        <>
            <div
                // This is a hack to make the meta info panel have a margin top of 0 when it's the first child of the panel
                className={`
                    [&+.scene-panel-meta-info]:mt-0 
                    flex flex-col gap-2 min-h-[var(--scene-layout-header-height)] py-2 border-b border-primary -mx-2 px-2 mb-2
                `}
            >
                {children}
            </div>
        </>
    )
}

// Should be second!
export function ScenePanelMetaInfo({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="scene-panel-meta-info pl-1 pb-1 flex flex-col gap-2 mt-2">{children}</div>
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
            <Label intent="menu" {...props}>
                {title}
            </Label>
            {children}
        </div>
    )
}
8

export function SceneLayout({ children, sceneConfig }: SceneLayoutProps): JSX.Element {
    const { registerScenePanelElement, setScenePanelOpen, setForceScenePanelClosedWhenRelative, setSceneLayoutConfig } =
        useActions(sceneLayoutLogic)
    const { useSceneTabs, forceScenePanelClosedWhenRelative } = useValues(sceneLayoutLogic)

    const { scenePanelIsPresent, scenePanelOpen, scenePanelIsRelative } = useValues(sceneLayoutLogic)

    // Set layout config
    useEffect(() => {
        if (sceneConfig) {
            setSceneLayoutConfig(sceneConfig)
        }
    }, [sceneConfig, setSceneLayoutConfig])

    return (
        <>
            <div
                className={cn(
                    'col-span-2 h-[var(--scene-layout-header-height)] sticky top-0 z-[var(--z-main-nav)] flex justify-center items-start',
                    {
                        'col-start-1 col-span-1': scenePanelIsRelative && !forceScenePanelClosedWhenRelative,
                    }
                )}
            >
                {useSceneTabs ? <SceneTabs /> : null}
            </div>

            <div
                className={cn('relative p-4', {
                    'col-start-1 col-span-1 w-[calc(100%-var(--scene-layout-panel-width))]':
                        scenePanelIsPresent && scenePanelIsRelative && !forceScenePanelClosedWhenRelative,
                    'p-0': sceneConfig?.layout === 'app-raw-no-header' || sceneConfig?.layout === 'app-raw',
                    'h-[calc(100vh-var(--scene-layout-header-height))]':
                        sceneConfig?.layout === 'app-full-scene-height',
                })}
            >
                {children}
            </div>

            {scenePanelIsPresent && (
                <>
                    <div
                        className={cn(
                            'scene-layout__content-panel fixed left-[calc(var(--scene-layout-rect-right)-var(--scene-layout-panel-width)+var(--scene-layout-scrollbar-width))] bg-surface-secondary flex flex-col overflow-hidden h-[calc(var(--scene-layout-rect-height)-var(--scene-layout-header-height))] top-[var(--scene-layout-header-height)] min-w-0',
                            {
                                hidden: !scenePanelOpen,
                                'col-start-2 col-span-1 row-start-1 row-span-2':
                                    scenePanelIsRelative && !forceScenePanelClosedWhenRelative,
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
                                >
                                    <IconX className="size-4" />
                                </ButtonPrimitive>
                            )}
                        </div>
                        <ScrollableShadows
                            direction="vertical"
                            className="h-full flex-1"
                            innerClassName="px-2 pb-4 bg-primary"
                            styledScrollbars
                        >
                            <div ref={registerScenePanelElement} />
                        </ScrollableShadows>
                    </div>

                    {scenePanelOpen && !scenePanelIsRelative && (
                        <div
                            onClick={() => {
                                setScenePanelOpen(false)
                            }}
                            aria-hidden="true"
                            className="z-[var(--z-scene-layout-content-panel-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-100"
                        />
                    )}
                </>
            )}
        </>
    )
}
