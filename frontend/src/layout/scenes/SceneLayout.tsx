import './SceneLayout.css'

import { useActions, useValues } from 'kea'
import React, { PropsWithChildren, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { LemonDivider } from '@posthog/lemon-ui'

import { ShortcutMenu } from 'lib/components/Shortcuts/ShortcutMenu'
import { Label, LabelProps } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { sceneLayoutLogic } from './sceneLayoutLogic'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    sceneConfig?: SceneConfig | null
}

export function ScenePanel({ children }: { children: React.ReactNode }): JSX.Element {
    const { scenePanelElement } = useValues(sceneLayoutLogic)
    const { registerScenePanel, unregisterScenePanel } = useActions(sceneLayoutLogic)
    const { activeSceneId } = useValues(sceneLogic)
    // The host is shared by every scene, so a panel may only write to it while the scene that
    // opened it is still on screen. Without this a scene that outlives its own scene change
    // keeps its actions in the panel under the next page.
    const ownerSceneId = useRef(activeSceneId)
    const ownsPanel = ownerSceneId.current === activeSceneId

    useEffect(() => {
        if (!ownsPanel) {
            return
        }
        registerScenePanel()
        return () => {
            unregisterScenePanel()
        }
    }, [ownsPanel, registerScenePanel, unregisterScenePanel])

    return (
        <>
            {ownsPanel &&
                children &&
                scenePanelElement &&
                createPortal(<div className="flex flex-col gap-2">{children}</div>, scenePanelElement)}
        </>
    )
}

export function ScenePanelDivider({ className }: { className?: string }): JSX.Element {
    return <LemonDivider className={cn('-mx-2 w-[calc(100%+1rem)]', className)} />
}

export function ScenePanelInfoSection({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="scene-panel-info-section flex flex-col gap-2">{children}</div>
}

export function ScenePanelActionsSection({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="scene-panel-actions-section flex flex-col gap-px -ml-1 pl-1">{children}</div>
}

export function ScenePanelLabel({
    children,
    title,
    className,
    ...props
}: PropsWithChildren<Omit<LabelProps, 'title'> & { title: React.ReactNode }>): JSX.Element {
    return (
        <div className="flex flex-col gap-0">
            <Label intent="menu" {...props} className={cn('text-tertiary/80', className)}>
                {title}
            </Label>
            {children}
        </div>
    )
}

export function SceneLayout({ children, sceneConfig }: SceneLayoutProps): JSX.Element {
    const { setSceneLayoutConfig } = useActions(sceneLayoutLogic)

    // Set layout config
    useEffect(() => {
        if (sceneConfig) {
            setSceneLayoutConfig(sceneConfig)
        }
    }, [sceneConfig, setSceneLayoutConfig])

    return (
        <>
            {children}

            <ShortcutMenu />
        </>
    )
}
