import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { featureFlagConfirmationSettingsLogic } from './featureFlagConfirmationSettingsLogic'

export function FlagPersistenceSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

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
        />
    )
}

export function FlagChangeConfirmationSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { confirmationMessageLoading } = useValues(featureFlagConfirmationSettingsLogic)

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
        <div className="space-y-2">
            <h3 className="mt-0 mb-1 text-sm font-semibold text-muted">
                Primary Key <span className="text-green-700 text-xs ml-2">(Active)</span>
            </h3>
            <CodeSnippet
                actions={
                    <LemonButton
                        icon={<IconRefresh />}
                        noPadding
                        onClick={openResetDialog}
                        disabledReason={
                            !isTeamTokenResetAvailable ? 'You do not have permission to rotate this key' : undefined
                        }
                        tooltip={currentTeam?.secret_api_token ? 'Rotate key' : 'Generate key'}
                    />
                }
                className={currentTeam?.secret_api_token ? '' : 'text-muted'}
                thing="Primary Feature Flags Secure API key"
            >
                {currentTeam?.secret_api_token || 'Click the rotate button on the right to generate a new key.'}
            </CodeSnippet>

            {currentTeam?.secret_api_token_backup ? (
                <>
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
