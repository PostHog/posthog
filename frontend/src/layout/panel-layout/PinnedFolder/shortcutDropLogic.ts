import { actions, connect, kea, listeners, path } from 'kea'

import { projectTreeDataLogic } from '../ProjectTree/projectTreeDataLogic'
import { pinnedFolderLogic } from './pinnedFolderLogic'
import type { shortcutDropLogicType } from './shortcutDropLogicType'

export const shortcutDropLogic = kea<shortcutDropLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'shortcutDropLogic']),

    connect(() => ({
        values: [pinnedFolderLogic, ['pinnedFolder']],
        actions: [pinnedFolderLogic, ['setPinnedFolder'], projectTreeDataLogic, ['addShortcutItem']],
    })),

    actions({
        handleShortcutDrop: (href: string, title?: string) => ({ href, title }),
    }),

    listeners(({ actions, values }) => ({
        handleShortcutDrop: ({ href, title }) => {
            const name = title || href.split('/').pop() || 'Untitled'

            // Create a shortcut item
            const shortcutItem = {
                id: `shortcut-${Date.now()}`,
                path: name,
                type: 'link' as const,
                href: href,
                ref: href,
            }

            actions.addShortcutItem(shortcutItem)

            // Switch to shortcuts view if not already there
            if (values.pinnedFolder !== 'shortcuts://') {
                actions.setPinnedFolder('shortcuts://')
            }
        },
    })),
])
