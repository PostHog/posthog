import './SceneLayout.css'

import { useActions, useValues } from 'kea'
import React, { PropsWithChildren, useEffect } from 'react'
import { createPortal } from 'react-dom'

import { LemonDivider } from '@posthog/lemon-ui'

import { AppShortcutMenu } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { Label, LabelProps } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'

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
                createPortal(<div className="flex flex-col gap-2">{children}</div>, scenePanelElement)}
        </>
    )
}

export function ScenePanelDivider({ className }: { className?: string }): JSX.Element {
    return <LemonDivider className={cn('-mx-2 w-[calc(100%+1rem)]', className)} />
}

export function ScenePanelInfoSection({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="scene-panel-info-section pl-1 flex flex-col gap-2">{children}</div>
}

export function ScenePanelActionsSection({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="scene-panel-actions-section flex flex-col gap-px -ml-1 pl-1">{children}</div>
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

            <AppShortcutMenu />
        </>
    )
}
