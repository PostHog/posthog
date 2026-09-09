import { useActions, useValues } from 'kea'

import { IconRefresh, IconTrash } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
    Card,
    CardContent,
} from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

export function SecretApiKeySection(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { rotateSecretToken, deleteSecretTokenBackup } = useActions(teamLogic)

    const verb = currentTeam?.secret_api_token ? 'Rotate' : 'Generate'
    const rotateDescription = currentTeam?.secret_api_token
        ? 'This will generate a new secret API key and move the existing one to backup. The old key will remain active until you delete it.'
        : 'This will generate a new secret API key for authenticating external API requests.'
    const rotateDisabledReason = !isTeamTokenResetAvailable
        ? 'You do not have permission to rotate this key'
        : undefined

    return (
        <SceneSection
            title="Secret API key"
            titleSize="sm"
            description="Authenticates workflow actions that read or update tickets, and signs identity hashes for identity verification. Project secret API keys can't be used for either."
        >
            <Card size="sm" className="max-w-[800px]">
                <CardContent className="flex flex-col gap-y-2">
                    <div>
                        <h3 className="text-sm font-semibold mb-1">
                            Primary key{' '}
                            {currentTeam?.secret_api_token && (
                                <span className="text-green-700 text-xs ml-2">(Active)</span>
                            )}
                        </h3>
                        <CodeSnippet
                            actions={
                                <AlertDialog>
                                    <AlertDialogTrigger
                                        render={
                                            <Button
                                                variant="default"
                                                size="icon-xs"
                                                disabled={!!rotateDisabledReason}
                                                title={
                                                    rotateDisabledReason ??
                                                    (currentTeam?.secret_api_token ? 'Rotate key' : 'Generate key')
                                                }
                                            />
                                        }
                                    >
                                        <IconRefresh />
                                    </AlertDialogTrigger>
                                    <AlertDialogContent>
                                        <AlertDialogHeader>
                                            <AlertDialogTitle>{verb} secret API key?</AlertDialogTitle>
                                            <AlertDialogDescription>{rotateDescription}</AlertDialogDescription>
                                        </AlertDialogHeader>
                                        <AlertDialogFooter>
                                            <AlertDialogClose render={<Button variant="outline" />}>
                                                Cancel
                                            </AlertDialogClose>
                                            <AlertDialogClose
                                                render={<Button variant="primary" onClick={rotateSecretToken} />}
                                            >
                                                {verb}
                                            </AlertDialogClose>
                                        </AlertDialogFooter>
                                    </AlertDialogContent>
                                </AlertDialog>
                            }
                            className={currentTeam?.secret_api_token ? '' : 'text-muted'}
                            thing="Secret API key"
                        >
                            {currentTeam?.secret_api_token ||
                                'No key yet — generate one with the button on the right to start using ticket workflow actions.'}
                        </CodeSnippet>
                    </div>

                    {currentTeam?.secret_api_token ? (
                        <div className="rounded border border-warning bg-warning-highlight p-2 text-sm my-2">
                            Rotating this key will require updating it everywhere it's used. Rotate if it has been
                            compromised or as part of your regular key rotation policy.
                        </div>
                    ) : (
                        <div className="rounded border border-warning bg-warning-highlight p-2 text-sm my-2">
                            This project doesn't have a secret API key yet. Workflow steps that get or update tickets
                            will fail until you generate one.
                        </div>
                    )}

                    {currentTeam?.secret_api_token_backup ? (
                        <div>
                            <h3 className="text-sm font-semibold mb-1">
                                Backup key <span className="text-orange-600 text-xs ml-2">(Pending deletion)</span>
                            </h3>
                            <CodeSnippet
                                actions={
                                    <Button
                                        variant="default"
                                        size="icon-xs"
                                        onClick={() => deleteSecretTokenBackup()}
                                        title="Delete backup key"
                                        aria-label="Delete backup key"
                                    >
                                        <IconTrash />
                                    </Button>
                                }
                                thing="Backup secret API key"
                            >
                                {currentTeam.secret_api_token_backup}
                            </CodeSnippet>
                            <p className="text-xs text-muted mt-1">
                                This key is still active to support services using the previous key. Delete it once
                                you've fully migrated.
                            </p>
                        </div>
                    ) : null}
                </CardContent>
            </Card>
        </SceneSection>
    )
}
