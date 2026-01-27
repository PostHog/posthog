import './SceneLayout.css'

import { useActions, useValues } from 'kea'
import React, { PropsWithChildren, useEffect } from 'react'
import { createPortal } from 'react-dom'

import { LemonDivider } from '@posthog/lemon-ui'

import { AppShortcutMenu } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Label, LabelProps } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'

import { sceneLayoutLogic } from './sceneLayoutLogic'

type SceneLayoutProps = {
    children: React.ReactNode
    className?: string
    sceneConfig?: SceneConfig | null
}

/**
 * ScenePanel renders content in the scene's side panel.
 * When UX_REMOVE_SIDEPANEL flag is off: Uses portal to render into scenePanelElement
 * When UX_REMOVE_SIDEPANEL flag is on: Renders children directly (handled by scenePanelTabs)
 */
export function ScenePanel({ children }: { children: React.ReactNode }): JSX.Element {
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')
    const { scenePanelElement } = useValues(sceneLayoutLogic)
    const { setScenePanelIsPresent } = useActions(sceneLayoutLogic)

    // Legacy: Register panel presence when flag is off
    useEffect(() => {
        if (!isRemovingSidePanelFlag) {
            setScenePanelIsPresent(true)
            return () => {
                setScenePanelIsPresent(false)
            }
        }
    }, [isRemovingSidePanelFlag, setScenePanelIsPresent])

    // When flag is on, render children directly (they're handled by inline rendering in scenes)
    if (isRemovingSidePanelFlag) {
        return <>{children}</>
    }

    // Legacy portal-based rendering when flag is off
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
