import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { HedgehogModeProfile } from 'lib/components/HedgehogMode/HedgehogModeStatic'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'

export function HedgehogModeSettings(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { updateRemoteConfig } = useActions(hedgehogModeLogic)
    return (
        <>
            <div className="flex gap-2">
                <HedgehogModeProfile config={hedgehogConfig} size={36} />
                <LemonSwitch
                    label="Enable hedgehog mode"
                    data-attr="hedgehog-mode-switch"
                    onChange={(checked) => updateRemoteConfig({ enabled: checked })}
                    checked={hedgehogConfig.enabled}
                    bordered
                />
                <LemonSwitch
                    label="Use as profile picture"
                    data-attr="hedgehog-profile-picture"
                    onChange={(checked) => updateRemoteConfig({ use_as_profile: checked })}
                    checked={hedgehogConfig.use_as_profile}
                    bordered
                />
            </div>
        </>
    )
}
