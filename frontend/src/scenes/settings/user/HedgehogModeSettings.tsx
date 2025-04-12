import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'

export function HedgehogModeSettings(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { patchHedgehogConfig } = useActions(hedgehogModeLogic)
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

            <div className="p-2 mt-4 border rounded bg-surface-primary">
                <p>TODO!</p>
            </div>
        </>
    )
}
