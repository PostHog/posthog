import { afterMount, connect, kea, path } from 'kea'

import { commandBarLogic } from './commandBarLogic'
import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['lib', 'components', 'CommandBar', 'shortcutsLogic']),

    connect(() => ({
        actions: [commandBarLogic, ['hideCommandBar']],
    })),
    afterMount(({ actions, cache }) => {
        // register keyboard shortcuts
        cache.disposables.add(() => {
            const onKeyDown = (event: KeyboardEvent): void => {
                if (event.key === 'Escape') {
                    // hide command bar
                    actions.hideCommandBar()
                }
            }
            window.addEventListener('keydown', onKeyDown)
            return () => window.removeEventListener('keydown', onKeyDown)
        }, 'escapeKeyListener')
    }),
])
