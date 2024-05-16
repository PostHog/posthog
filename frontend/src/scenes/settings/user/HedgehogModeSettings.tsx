import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { HedgehogOptions } from 'lib/components/HedgehogBuddy/HedgehogOptions'

export function HedgehogModeSettings(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogBuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogBuddyLogic)
    return (
        <>
            <LemonSwitch
                label="Enabled hedgehog mode"
                data-attr="hedgehog-mode-switch"
                onChange={(checked) => setHedgehogModeEnabled(checked)}
                checked={hedgehogModeEnabled}
                bordered
            />

            <div className="mt-4 p-2 border rounded bg-accent-3000">
                <HedgehogOptions />
            </div>
        </>
    )
}
