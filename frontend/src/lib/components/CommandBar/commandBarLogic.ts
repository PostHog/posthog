import { kea, path, actions, reducers, afterMount, beforeUnmount } from 'kea'
import { BarStatus } from './types'

import type { commandBarLogicType } from './commandBarLogicType'

export const commandBarLogic = kea<commandBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'commandBarLogic']),
    actions({
        setCommandBar: (status: BarStatus) => ({ status }),
        hideCommandBar: true,
        toggleSearchBar: true,
        toggleActionsBar: true,
    }),
    reducers({
        barStatus: [
            BarStatus.HIDDEN as BarStatus,
            {
                setCommandBar: (_, { status }) => status,
                hideCommandBar: () => BarStatus.HIDDEN,
                toggleSearchBar: (previousState) =>
                    previousState === BarStatus.HIDDEN ? BarStatus.SHOW_SEARCH : BarStatus.HIDDEN,
                toggleActionsBar: (previousState) =>
                    previousState === BarStatus.HIDDEN ? BarStatus.SHOW_ACTIONS : BarStatus.HIDDEN,
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
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ cache }) => {
        // unregister keyboard shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])
