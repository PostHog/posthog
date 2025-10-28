import { useActions, useValues } from 'kea'

import { HedgeHogMode, HedgehogCustomization, HedgehogModeRendererContent } from '@posthog/hedgehog-mode'
import { LemonSwitch } from '@posthog/lemon-ui'

import { getHedgehogModeAssetsUrl } from 'lib/components/HedgehogMode/HedgehogMode'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'

export function HedgehogModeSettings(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { updateRemoteConfig } = useActions(hedgehogModeLogic)
    return (
        <>
            <div className="flex gap-2">
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

            <div className="border rounded mt-2 bg-surface-primary p-3">
                <HedgehogModeRendererContent id="hedgehog-customization">
                    <HedgehogCustomization
                        config={hedgehogConfig.actor_options}
                        setConfig={(config) => updateRemoteConfig({ actor_options: config })}
                        game={
                            new HedgeHogMode({
                                assetsUrl: getHedgehogModeAssetsUrl(),
                            })
                        }
                    />
                </HedgehogModeRendererContent>
            </div>
        </>
    )
}
