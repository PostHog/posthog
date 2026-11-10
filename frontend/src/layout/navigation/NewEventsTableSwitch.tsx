import { useActions, useValues } from 'kea'

import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'

import { newEventsTableLogic } from './newEventsTableLogic'

export function NewEventsTableSwitch(): JSX.Element | null {
    const { newEventsTableAvailable, newEventsTableEnabled } = useValues(newEventsTableLogic)
    const { setNewEventsTable } = useActions(newEventsTableLogic)

    if (!newEventsTableAvailable) {
        return null
    }

    return (
        <LemonSwitch
            checked={newEventsTableEnabled}
            onChange={setNewEventsTable}
            label="New events table"
            fullWidth
            className="px-2 py-1"
            data-attr="new-events-table-switch"
        />
    )
}
