import { actions, connect, kea, listeners, path } from 'kea'

import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { SceneShortcutProps } from 'lib/components/Scenes/SceneShortcut/SceneShortcut'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['lib', 'shortcutsLogic']),
    connect(() => ({
        values: [sceneLogic, ['activeTab'], commandBarLogic, ['barStatus']],
    })),

    actions({
        triggerNewTab: true,
        triggerCloseCurrentTab: true,
        toggleSearchBar: true,
    }),

    listeners(({ values }) => ({
        triggerNewTab: () => {
            sceneLogic.actions.newTab()
        },
        toggleSearchBar: () => {
            commandBarLogic.actions.toggleSearchBar()
        },
        triggerCloseCurrentTab: () => {
            if (values.activeTab) {
                sceneLogic.actions.removeTab(values.activeTab)
            }
        },
    })),
])

type ShortcutDefinition = Omit<SceneShortcutProps, 'children'> & {
    active?: () => boolean // Allow active to be a function in the definition
}

type SceneShortcuts = {
    app: Record<string, ShortcutDefinition>
} & {
    [key in Scene]?: Record<string, ShortcutDefinition>
}

export const SHORTCUTS: SceneShortcuts = {
    app: {
        // Here we define shortcuts that are available in all scenes
        newTab: {
            keys: ['command', 'option', 't'],
            description: 'New tab',
            onAction: () => shortcutsLogic.actions.triggerNewTab(),
            order: -2,
        },
        closeCurrentTab: {
            keys: ['command', 'option', 'w'],
            description: 'Close current tab',
            onAction: () => shortcutsLogic.actions.triggerCloseCurrentTab(),
            order: -1,
        },
        toggleSearchBar: {
            keys: ['command', 'option', 'k'],
            description: 'Toggle search bar',
            onAction: () => {
                shortcutsLogic.actions.toggleSearchBar()
            },
            type: 'toggle',
        },
    },
    // Here we define shortcuts that are available in specific scenes
    [Scene.Dashboard]: {
        toggleEditMode: {
            keys: ['command', 'option', 'e'],
            description: 'Toggle dashboard edit mode',
            sceneKey: Scene.Dashboard,
        },
    },
}
