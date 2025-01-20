import { LemonDialog, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

export type FeatureFlagSettingsProps = {
    inModal?: boolean
}

export function FeatureFlagSettings({ inModal = false }: FeatureFlagSettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <LemonSwitch
                    data-attr="default-flag-persistence-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            flags_persistence_default: checked,
                        })
                    }}
                    label="Enable flag persistence by default"
                    bordered={!inModal}
                    fullWidth={inModal}
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    checked={!!currentTeam?.flags_persistence_default}
                />

                <p>
                    When enabled, all new feature flags will have persistence enabled by default. This ensures
                    consistent user experiences across authentication steps. Learn more in our{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                        target="_blank"
                    >
                        documentation
                    </Link>
                    .
                </p>
            </div>
        </div>
    )
}

export function openFeatureFlagSettingsDialog(): void {
    LemonDialog.open({
        title: 'Feature flag settings',
        content: <FeatureFlagSettings inModal />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
