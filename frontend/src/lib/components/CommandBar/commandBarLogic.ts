import { actions, connect, kea, path, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

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
])
