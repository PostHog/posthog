import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'

import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { newEventsTableLogic } from './newEventsTableLogic'

export function NewEventsTableControls(): JSX.Element | null {
    const { newEventsTableAvailable, newEventsTableEnabled } = useValues(newEventsTableLogic)
    const { setNewEventsTable, openEventsTableTab } = useActions(newEventsTableLogic)

    if (!newEventsTableAvailable) {
        return null
    }

    return (
        <>
            <LemonSwitch
                checked={newEventsTableEnabled}
                onChange={setNewEventsTable}
                label="New events table"
                fullWidth
                className="px-2 py-1"
                data-attr="new-events-table-switch"
            />
            <ButtonPrimitive
                menuItem
                autoHeight
                className="py-1.5"
                onClick={() => openEventsTableTab(true)}
                data-attr="new-events-table-open-new"
            >
                <IconExternal />
                Open this page with new events table
            </ButtonPrimitive>
            <ButtonPrimitive
                menuItem
                autoHeight
                className="py-1.5"
                onClick={() => openEventsTableTab(false)}
                data-attr="new-events-table-open-classic"
            >
                <IconExternal />
                Open this page with classic events table
            </ButtonPrimitive>
        </>
    )
}
