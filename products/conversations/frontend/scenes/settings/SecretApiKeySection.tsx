import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

export function SecretApiKeySection(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { rotateSecretToken, deleteSecretTokenBackup } = useActions(teamLogic)

    const rotateDisabledReason = !isTeamTokenResetAvailable
        ? 'Only project admins can generate or rotate this key. Ask a project admin for help.'
        : undefined

    const openRotateDialog = (): void => {
        const verb = currentTeam?.secret_api_token ? 'Rotate' : 'Generate'
        const description = currentTeam?.secret_api_token
            ? 'This will generate a new secret API key and move the existing one to backup. The old key will remain active until you delete it.'
            : 'This will generate a new secret API key for authenticating external API requests.'

        LemonDialog.open({
            title: `${verb} secret API key?`,
            description,
            primaryButton: {
                children: verb,
                onClick: rotateSecretToken,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneSection
            title="Secret API key"
            titleSize="sm"
            description="Authenticates workflow actions that read or update tickets, and signs identity hashes for identity verification. Project secret API keys can't be used for either."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <div>
                    <h3 className="text-sm font-semibold mb-1">
                        Primary key{' '}
                        {currentTeam?.secret_api_token && <span className="text-green-700 text-xs ml-2">(Active)</span>}
                    </h3>
                    {currentTeam?.secret_api_token ? (
                        <CodeSnippet
                            actions={
                                <LemonButton
                                    icon={<IconRefresh />}
                                    size="xsmall"
                                    onClick={openRotateDialog}
                                    disabledReason={rotateDisabledReason}
                                    tooltip="Rotate key"
                                    data-attr="support-secret-api-key-rotate"
                                />
                            }
                            thing="Secret API key"
                        >
                            {currentTeam.secret_api_token}
                        </CodeSnippet>
                    ) : (
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={openRotateDialog}
                            disabledReason={rotateDisabledReason}
                            data-attr="support-secret-api-key-generate"
                        >
                            Generate secret API key
                        </LemonButton>
                    )}
                </div>

                {currentTeam?.secret_api_token ? (
                    <LemonBanner type="warning" className="my-2">
                        Rotating this key will require updating it everywhere it's used. Rotate if it has been
                        compromised or as part of your regular key rotation policy.
                    </LemonBanner>
                ) : (
                    <LemonBanner type="warning" className="my-2">
                        This project doesn't have a secret API key yet. Workflow steps that get or update tickets will
                        fail until you generate one.
                    </LemonBanner>
                )}

                {currentTeam?.secret_api_token_backup ? (
                    <div>
                        <h3 className="text-sm font-semibold mb-1">
                            Backup key <span className="text-orange-600 text-xs ml-2">(Pending deletion)</span>
                        </h3>
                        <CodeSnippet
                            actions={
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="xsmall"
                                    onClick={() => deleteSecretTokenBackup()}
                                    tooltip="Delete backup key"
                                />
                            }
                            thing="Backup secret API key"
                        >
                            {currentTeam.secret_api_token_backup}
                        </CodeSnippet>
                        <p className="text-xs text-muted mt-1">
                            This key is still active to support services using the previous key. Delete it once you've
                            fully migrated.
                        </p>
                    </div>
                ) : null}
            </LemonCard>
        </SceneSection>
    )
}
