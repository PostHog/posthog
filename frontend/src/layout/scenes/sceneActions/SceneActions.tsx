import { useValues } from 'kea'
import { useContext, useEffect } from 'react'
import { createPortal } from 'react-dom'

import { SetupReminderContext } from 'lib/components/ProductEmptyState/setupReminderContext'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { captureSceneMenuBar } from '../components/captureSceneMenuBar'
import { SceneMenuBar } from '../components/SceneMenuBar'
import {
    useFillSceneMenuBarSlot,
    useFillScenePinnedSlot,
    useSceneMenuBarSlot,
    useScenePinnedSlot,
} from '../components/SceneMenuBarSlotProvider'
import { SceneActionMenu } from './SceneActionMenu'
import type { SceneAction, SceneActionGroup } from './sceneActionModel'
import { SceneActionsLegacyMenus } from './SceneActionsLegacyMenus'
import { ScenePinnedActions } from './ScenePinnedActions'
import { useSceneHelpActions } from './useSceneHelpActions'

interface SceneActionsProps {
    actions: SceneAction[]
    dataAttrKey?: string
    /** A menu `data-attr` that predates the `${dataAttrKey}-menubar-${group}` pattern. Analytics depend on it. */
    menuDataAttrs?: Partial<Record<SceneActionGroup, string>>
    className?: string
}

/**
 * A scene's actions, declared once. Render it where the scene rendered its menu bar, above `SceneTitleSection`.
 *
 * Under `today-rail-nav` with `scene-actions` on, a titled scene gets the "More actions" menu after its name and its
 * pinned actions in the title row, in place of the title's own `actions`. Everywhere else the actions render through
 * the menu bar primitives, as the scene's menu bar did.
 */
export function SceneActions({ actions, dataAttrKey, menuDataAttrs, className }: SceneActionsProps): JSX.Element {
    const sceneActionsEnabled = useFeatureFlag('SCENE_ACTIONS')
    const { todayRailEnabled } = useValues(todayShellLogic)
    const menuSlot = useSceneMenuBarSlot()
    const pinnedSlot = useScenePinnedSlot()
    const modelShown = sceneActionsEnabled && todayRailEnabled && !!menuSlot

    if (!modelShown) {
        return (
            <SceneMenuBar className={className}>
                <SceneActionsLegacyMenus actions={actions} dataAttrKey={dataAttrKey} menuDataAttrs={menuDataAttrs} />
            </SceneMenuBar>
        )
    }
    return (
        <SceneActionsModel
            actions={actions}
            dataAttrKey={dataAttrKey}
            menuDataAttrs={menuDataAttrs}
            menuSlot={menuSlot}
            pinnedSlot={pinnedSlot}
        />
    )
}

function SceneActionsModel({
    actions,
    dataAttrKey,
    menuDataAttrs,
    menuSlot,
    pinnedSlot,
}: Omit<SceneActionsProps, 'className'> & {
    menuSlot: HTMLElement
    pinnedSlot: HTMLElement | null
}): JSX.Element {
    const helpActions = useSceneHelpActions()
    const setupReminder = useContext(SetupReminderContext)
    useFillSceneMenuBarSlot(true)
    useFillScenePinnedSlot(!!pinnedSlot)

    useEffect(() => {
        // pinned: analytics property values are wire strings
        captureSceneMenuBar('scene menu bar shown', { layout: 'scene-actions' })
    }, [])

    return (
        <>
            {createPortal(
                <SceneActionMenu
                    actions={[...actions, ...helpActions]}
                    dataAttrKey={dataAttrKey}
                    menuDataAttrs={menuDataAttrs}
                />,
                menuSlot
            )}
            {pinnedSlot && createPortal(<ScenePinnedActions actions={actions} />, pinnedSlot)}
            {setupReminder}
        </>
    )
}
