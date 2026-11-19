import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { outOfOfficeLogic } from './outOfOfficeLogic'

export function OutOfOfficeSwitch(): JSX.Element | null {
    const { enabled, myEntry, awaySaving, entriesLoading } = useValues(outOfOfficeLogic)
    const { setAway } = useActions(outOfOfficeLogic)

    if (!enabled) {
        return null
    }
    return (
        <LemonSwitch
            bordered
            size="small"
            label="Out of office"
            checked={!!myEntry}
            loading={awaySaving}
            disabledReason={entriesLoading ? 'Loading…' : undefined}
            onChange={setAway}
            tooltip={
                myEntry
                    ? `Out of office since ${humanFriendlyDetailedTime(myEntry.since)}. Turn it off when you're back.`
                    : 'Turn on while you are away. Teammates see "Away" next to your name when they assign tickets.'
            }
            data-attr="support-out-of-office-switch"
        />
    )
}
