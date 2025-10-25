import { actions, afterMount, connect, kea, path, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { shouldIgnoreInput } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import type { commandBarLogicType } from './commandBarLogicType'
import { BarStatus } from './types'

export const commandBarLogic = kea<commandBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'commandBarLogic']),

    connect(() => ({
        actions: [eventUsageLogic, ['reportCommandBarStatusChanged']],
    })),
    actions({
        setCommandBar: (status: BarStatus, initialQuery?: string) => ({ status, initialQuery }),
        hideCommandBar: true,
        toggleSearchBar: true,
        toggleActionsBar: true,
        toggleShortcutOverview: true,
        clearInitialQuery: true,
    }),
    reducers({
        barStatus: [
            BarStatus.HIDDEN as BarStatus,
            {
                setCommandBar: (_, { status }) => status,
                hideCommandBar: () => BarStatus.HIDDEN,
                toggleSearchBar: (previousState) =>
                    previousState === BarStatus.SHOW_SEARCH ? BarStatus.HIDDEN : BarStatus.SHOW_SEARCH,
                toggleActionsBar: (previousState) =>
                    previousState === BarStatus.SHOW_ACTIONS ? BarStatus.HIDDEN : BarStatus.SHOW_ACTIONS,
                toggleShortcutOverview: (previousState) =>
                    previousState === BarStatus.HIDDEN ? BarStatus.SHOW_SHORTCUTS : previousState,
            },
        ],
        initialQuery: [
            null as string | null,
            {
                setCommandBar: (_, { initialQuery }) => initialQuery || null,
                clearInitialQuery: () => null,
            },
        ],
    }),
    subscriptions(({ actions }) => ({
        barStatus: (status, prevStatus) => {
            if (prevStatus !== undefined) {
                actions.reportCommandBarStatusChanged(status)
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        // register keyboard shortcuts
        cache.disposables.add(() => {
            const onKeyDown = (event: KeyboardEvent): void => {
                if (shouldIgnoreInput(event)) {
                    return
                }
                if ((event.ctrlKey || event.metaKey) && (event.key === 'k' || event.key === 'K')) {
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
            window.addEventListener('keydown', onKeyDown)
            return () => window.removeEventListener('keydown', onKeyDown)
        }, 'keyboardShortcuts')
    }),
])
