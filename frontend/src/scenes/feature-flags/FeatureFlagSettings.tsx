import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { teamLogic } from 'scenes/teamLogic'

export type FeatureFlagSettingsProps = {
    inModal?: boolean
}

export function FeatureFlagSettings({ inModal = false }: FeatureFlagSettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-8">
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
                        This key is still active to support deployments using the previous key. Delete it once you’ve
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
