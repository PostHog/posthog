import './SceneLayout.css'

import { useActions } from 'kea'
import React, { PropsWithChildren, useEffect } from 'react'

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

/**
 * @deprecated Use `scenePanelTabs` in sceneConfig instead. This portal-based approach
 * will be removed once all scenes are migrated to the declarative pattern.
 * See scenes.ts Scene.Surveys for an example of the new pattern.
 */
export function ScenePanel({ children }: { children: React.ReactNode }): JSX.Element {
    // Legacy portal-based implementation - kept for backward compatibility
    // TODO: Migrate all usages to scenePanelTabs in sceneConfig
    return <>{children}</>
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
