import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { newEventsTableLogic } from './newEventsTableLogic'

export function NewEventsTableBar(): JSX.Element | null {
    const { newEventsTableActive, newEventsTableBarDismissed, tabNewEventsTable } = useValues(newEventsTableLogic)
    const { setNewEventsTable, dismissNewEventsTableBar } = useActions(newEventsTableLogic)

    if (!newEventsTableActive || newEventsTableBarDismissed) {
        return null
    }

    return (
        <div className="fixed inset-x-2 bottom-2 z-[var(--z-bottom-notice)] mx-auto max-w-xl rounded shadow">
            <LemonBanner
                type="warning"
                action={{
                    children: 'Switch back',
                    onClick: () => setNewEventsTable(false),
                    'data-attr': 'new-events-table-bar-switch-back',
                }}
                onClose={dismissNewEventsTableBar}
            >
                {tabNewEventsTable === null
                    ? 'This browser is reading the new events table.'
                    : 'This browser tab is reading the new events table.'}
            </LemonBanner>
        </div>
    )
}
