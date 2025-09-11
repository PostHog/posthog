import { afterMount, beforeUnmount, connect, kea, path } from 'kea'

import { commandBarLogic } from './commandBarLogic'
import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['lib', 'components', 'CommandBar', 'shortcutsLogic']),
    connect(() => ({
        actions: [commandBarLogic, ['hideCommandBar']],
    })),
    afterMount(({ actions, cache }) => {
        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                // hide command bar
                actions.hideCommandBar()
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ cache }) => {
        // unregister keyboard shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])
