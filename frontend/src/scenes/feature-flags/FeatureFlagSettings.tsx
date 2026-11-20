import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDialog, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { featureFlagConfirmationSettingsLogic } from './featureFlagConfirmationSettingsLogic'

export function FlagPersistenceSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <LemonSwitch
            data-attr="default-flag-persistence-switch"
            onChange={(checked) => {
                updateCurrentTeam({
                    flags_persistence_default: checked,
                })
            }}
            label="Enable flag persistence by default"
            bordered
            checked={!!currentTeam?.flags_persistence_default}
            disabledReason={restrictedReason}
        />
    )
}

export function FlagChangeConfirmationSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { confirmationMessageLoading } = useValues(featureFlagConfirmationSettingsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="space-y-2">
            <LemonSwitch
                data-attr="feature-flag-confirmation-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        feature_flag_confirmation_enabled: checked,
                    })
                }}
                label="Require confirmation for feature flag changes"
                bordered
                checked={!!currentTeam?.feature_flag_confirmation_enabled}
                disabledReason={restrictedReason}
            />

            {currentTeam?.feature_flag_confirmation_enabled && (
                <div className="mt-4">
                    <Form
                        logic={featureFlagConfirmationSettingsLogic}
                        formKey="confirmationMessageForm"
                        enableFormOnSubmit
                        className="w-full"
                    >
                        <LemonField name="message" label="Custom confirmation message">
                            <LemonTextArea
                                placeholder="Optional custom message. Default: '⚠️ These changes will immediately affect users matching the release conditions. Please ensure you understand the consequences before proceeding.'"
                                maxLength={500}
                                maxRows={3}
                                disabled={!!restrictedReason}
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabledReason={!currentTeam ? 'Loading team...' : restrictedReason}
                            loading={confirmationMessageLoading}
                        >
                            Save message
                        </LemonButton>
                    </Form>
                </div>
            )}
        </div>
    )
}

export function FeatureFlagSettings(): JSX.Element {
    return (
        <div className="space-y-8">
            <FlagPersistenceSettings />
            <FlagChangeConfirmationSettings />
        </div>
    )
}

export function openFeatureFlagSettingsDialog(): void {
    LemonDialog.open({
        title: 'Feature flag settings',
        content: <FeatureFlagSettings />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
