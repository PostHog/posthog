import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'
import { useId } from 'react'

import { LemonButton, LemonDialog, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'
import { Button, Field, FieldError, FieldLabel, Switch, Textarea } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({
            flags_persistence_default: checked,
        })
    }

    if (todayRailNav) {
        return (
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    data-attr="default-flag-persistence-switch"
                    checked={!!currentTeam?.flags_persistence_default}
                    onCheckedChange={handleChange}
                    disabledReason={restrictedReason}
                />
                <FieldLabel htmlFor={switchId}>Enable flag persistence by default</FieldLabel>
            </Field>
        )
    }

    return (
        <LemonSwitch
            data-attr="default-flag-persistence-switch"
            onChange={handleChange}
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({
            feature_flag_confirmation_enabled: checked,
        })
    }

    const confirmationPlaceholder =
        "Optional custom message. Default: '⚠️ These changes will immediately affect users matching the release conditions. Please ensure you understand the consequences before proceeding.'"
    const saveDisabledReason = !currentTeam ? 'Loading team...' : restrictedReason

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <Field orientation="horizontal" className="w-fit">
                    <Switch
                        id={switchId}
                        data-attr="feature-flag-confirmation-switch"
                        checked={!!currentTeam?.feature_flag_confirmation_enabled}
                        onCheckedChange={handleChange}
                        disabledReason={restrictedReason}
                    />
                    <FieldLabel htmlFor={switchId}>Require confirmation for feature flag changes</FieldLabel>
                </Field>

                {currentTeam?.feature_flag_confirmation_enabled && (
                    <Form
                        logic={featureFlagConfirmationSettingsLogic}
                        formKey="confirmationMessageForm"
                        enableFormOnSubmit
                        className="flex w-full flex-col items-start gap-2"
                    >
                        <KeaField name="message" noStyle>
                            {({ id, value, onChange, error }) => (
                                <Field data-invalid={error ? true : undefined} className="w-full">
                                    <FieldLabel htmlFor={id}>Custom confirmation message</FieldLabel>
                                    <Textarea
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder={confirmationPlaceholder}
                                        maxLength={500}
                                        rows={3}
                                        disabledReason={restrictedReason}
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                        <Button
                            variant="primary"
                            type="submit"
                            disabledReason={saveDisabledReason}
                            loading={confirmationMessageLoading}
                        >
                            Save message
                        </Button>
                    </Form>
                )}
            </div>
        )
    }

    return (
        <div className="space-y-2">
            <LemonSwitch
                data-attr="feature-flag-confirmation-switch"
                onChange={handleChange}
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
                                placeholder={confirmationPlaceholder}
                                maxLength={500}
                                maxRows={3}
                                disabled={!!restrictedReason}
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            disabledReason={saveDisabledReason}
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
