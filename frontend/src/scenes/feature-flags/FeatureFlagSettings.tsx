import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, LemonTextArea, Link } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { teamLogic } from 'scenes/teamLogic'

import { DefaultEvaluationEnvironments } from './DefaultEvaluationEnvironments'
import { featureFlagConfirmationSettingsLogic } from './featureFlagConfirmationSettingsLogic'

export type FeatureFlagSettingsProps = {
    inModal?: boolean
}

export function FeatureFlagSettings({ inModal = false }: FeatureFlagSettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { confirmationMessageLoading } = useValues(featureFlagConfirmationSettingsLogic)

    return (
        <div className="space-y-8">
            <div className="space-y-2">
                <h3 className="min-w-[25rem]">Flag Persistence</h3>

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
            </div>

            <div className="space-y-2">
                <h3 className="min-w-[25rem]">Flag Change Confirmation</h3>

                <p>
                    When enabled, editing existing feature flags will show a confirmation modal before saving changes.
                    This helps prevent accidental changes to flag release conditions that could impact your users'
                    experience.
                </p>

                <LemonSwitch
                    data-attr="feature-flag-confirmation-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            feature_flag_confirmation_enabled: checked,
                        })
                    }}
                    label="Require confirmation for feature flag changes"
                    bordered={!inModal}
                    fullWidth={inModal}
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    checked={!!currentTeam?.feature_flag_confirmation_enabled}
                />

                {currentTeam?.feature_flag_confirmation_enabled && (
                    <div className="mt-4">
                        <Form
                            logic={featureFlagConfirmationSettingsLogic}
                            formKey="confirmationMessageForm"
                            enableFormOnSubmit
                            className="w-full"
                        >
                            <LemonField
                                name="message"
                                label="Custom confirmation message"
                                // help="Enter an optional custom message to show in the confirmation modal. If empty, the default message will be: '⚠️ These changes will immediately affect users matching the release conditions. Please ensure you understand the consequences before proceeding.'"
                            >
                                <LemonTextArea
                                    placeholder="Optional custom message. Default: '⚠️ These changes will immediately affect users matching the release conditions. Please ensure you understand the consequences before proceeding.'"
                                    maxLength={500}
                                    maxRows={3}
                                />
                            </LemonField>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                disabledReason={!currentTeam ? 'Loading team...' : undefined}
                                loading={confirmationMessageLoading}
                            >
                                Save message
                            </LemonButton>
                        </Form>
                    </div>
                )}
            </div>

            <div className="space-y-2">
                <DefaultEvaluationEnvironments />
            </div>

            <div className="space-y-2">
                <FlagsSecureApiKeys />
            </div>
        </div>
    )
}

export function FlagsSecureApiKeys(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { deleteSecretTokenBackup, rotateSecretToken } = useActions(teamLogic)

    const openResetDialog = (): void => {
        const verb = currentTeam?.secret_api_token ? 'Rotate' : 'Generate'
        const description =
            'This will generate a new Feature Flags secure API key' +
            (currentTeam?.secret_api_token
                ? ' and move the existing one to backup. The old key will remain active until you delete it.'
                : '')

        LemonDialog.open({
            title: `${verb} Flag Definitions API key?`,
            description: description,
            primaryButton: {
                children: verb,
                type: 'primary',
                onClick: rotateSecretToken,
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'secondary',
            },
        })
    }

    const openDeleteBackupDialog = (): void => {
        LemonDialog.open({
            title: 'Delete Backup API key?',
            description: 'This will permanently delete the previous key. Make sure your systems are using the new key.',
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: deleteSecretTokenBackup,
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'secondary',
            },
        })
    }

    return (
        <>
            <h2 id="secret-api-key" className="min-w-[25rem]">
                Feature Flags Secure API key
            </h2>

            <p>
                Use this key to retrieve feature flag definitions for{' '}
                <Link to="https://posthog.com/docs/feature-flags/local-evaluation">local evaluation</Link> or{' '}
                <Link to="https://posthog.com/docs/feature-flags/remote-config">remote config settings</Link>.
            </p>

            {/* Primary Key */}
            <h3 className="mt-4 mb-1 text-sm font-semibold text-muted">
                Primary Key <span className="text-green-700 text-xs ml-2">(Active)</span>
            </h3>
            <CodeSnippet
                actions={
                    isTeamTokenResetAvailable ? (
                        <LemonButton
                            icon={<IconRefresh />}
                            noPadding
                            onClick={openResetDialog}
                            tooltip={currentTeam?.secret_api_token ? 'Rotate key' : 'Generate key'}
                        />
                    ) : undefined
                }
                className={currentTeam?.secret_api_token ? '' : 'text-muted'}
                thing="Primary Feature Flags Secure API key"
            >
                {currentTeam?.secret_api_token || 'Click the rotate button on the right to generate a new key.'}
            </CodeSnippet>

            {currentTeam?.secret_api_token_backup ? (
                <>
                    {/* Backup Key */}
                    <h3 className="mt-4 mb-1 text-sm font-semibold text-muted">
                        Backup Key <span className="text-orange-600 text-xs ml-2">(Pending deletion)</span>
                    </h3>
                    <CodeSnippet
                        actions={
                            <LemonButton
                                icon={<IconTrash />}
                                noPadding
                                status="danger"
                                onClick={openDeleteBackupDialog}
                                tooltip="Delete backup key"
                            />
                        }
                        thing="Backup Feature Flags Secure API key"
                    >
                        {currentTeam.secret_api_token_backup}
                    </CodeSnippet>
                    <p className="text-xs text-muted mt-1">
                        This key is still active to support deployments using the previous key. Delete it once you've
                        fully migrated.
                    </p>
                </>
            ) : (
                <p className="text-xs text-muted mt-2">
                    Rotating the key will move this primary key to backup so you can migrate safely.
                </p>
            )}

            <p className="mt-4">
                This key replaces personal API keys for local evaluation. Existing personal API keys will continue to
                work, but we recommend migrating to this new key. Keep this key private.
            </p>
        </>
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
