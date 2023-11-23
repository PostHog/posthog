import { actions, afterMount, beforeUnmount, kea, path, reducers } from 'kea'

import type { commandBarLogicType } from './commandBarLogicType'
import { BarStatus } from './types'

export const commandBarLogic = kea<commandBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'commandBarLogic']),
    actions({
        setCommandBar: (status: BarStatus) => ({ status }),
        hideCommandBar: true,
        toggleSearchBar: true,
        toggleActionsBar: true,
        toggleShortcutOverview: true,
    }),
    reducers({
        barStatus: [
            BarStatus.HIDDEN as BarStatus,
            {
                setCommandBar: (_, { status }) => status,
                hideCommandBar: () => BarStatus.HIDDEN,
                toggleSearchBar: (previousState) =>
                    [BarStatus.HIDDEN, BarStatus.SHOW_SHORTCUTS].includes(previousState)
                        ? BarStatus.SHOW_SEARCH
                        : BarStatus.HIDDEN,
                toggleActionsBar: (previousState) =>
                    [BarStatus.HIDDEN, BarStatus.SHOW_SHORTCUTS].includes(previousState)
                        ? BarStatus.SHOW_ACTIONS
                        : BarStatus.HIDDEN,
                toggleShortcutOverview: (previousState) =>
                    previousState === BarStatus.HIDDEN ? BarStatus.SHOW_SHORTCUTS : previousState,
            },
        ],
    }),
    afterMount(({ actions, cache }) => {
        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
                event.preventDefault()
                if (event.shiftKey) {
                    // cmd+shift+k opens actions
                    actions.toggleActionsBar()
                } else {
                    // cmd+k opens search
                    actions.toggleSearchBar()
                }
            } else if (event.shiftKey && event.key === '?') {
                actions.toggleShortcutOverview()
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ cache }) => {
        // unregister keyboard shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])
