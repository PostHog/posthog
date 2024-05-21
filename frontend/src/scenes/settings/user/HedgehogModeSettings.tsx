import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { HedgehogOptions } from 'lib/components/HedgehogBuddy/HedgehogOptions'

export function HedgehogModeSettings(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)
    return (
        <>
            <div className="flex gap-2">
                <LemonSwitch
                    label="Enabled hedgehog mode"
                    data-attr="hedgehog-mode-switch"
                    onChange={(checked) => patchHedgehogConfig({ enabled: checked })}
                    checked={hedgehogConfig.enabled}
                    bordered
                />
                <LemonSwitch
                    label="Use as profile picture"
                    data-attr="hedgehog-profile-picture"
                    onChange={(checked) => patchHedgehogConfig({ use_as_profile: checked })}
                    checked={hedgehogConfig.use_as_profile}
                    bordered
                />
            </div>

            <div className="mt-4 p-2 border rounded bg-accent-3000">
                <HedgehogOptions />
            </div>
        </>
    )
}
