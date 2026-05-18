import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, Link } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { deploymentsLogic } from '../deploymentsLogic'
import { addProjectLogic } from './addProjectLogic'

export function AddProjectModal(): JSX.Element {
    const { addProjectModalOpen } = useValues(deploymentsLogic)
    const { closeAddProjectModal } = useActions(deploymentsLogic)
    const { integrationId, repoName, name, slug, submitting, error, githubIntegrations, canSubmit } =
        useValues(addProjectLogic)
    const { setIntegrationId, setRepoName, setName, setSlug, submit, reset } = useActions(addProjectLogic)

    const handleClose = (): void => {
        closeAddProjectModal()
        reset()
    }

    const noIntegrations = githubIntegrations.length === 0

    return (
        <LemonModal
            isOpen={addProjectModalOpen}
            onClose={handleClose}
            title="Add a deployment project"
            description="Connect a GitHub repository. PostHog will create a Cloudflare-backed deployment for it and run the first build on save."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={submitting ? 'Saving…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submit()}
                        loading={submitting}
                        disabledReason={!canSubmit ? 'Fill in all fields' : undefined}
                        data-attr="add-deployment-project-submit"
                    >
                        Create & deploy
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3 min-w-[28rem]">
                {noIntegrations ? (
                    <LemonBanner type="warning">
                        Install the GitHub integration first.{' '}
                        <Link to={urls.settings('environment-integrations')}>Open integration settings →</Link>
                    </LemonBanner>
                ) : (
                    <>
                        <LemonField.Pure label="GitHub integration">
                            <LemonSelect
                                value={integrationId}
                                onChange={(id) => setIntegrationId(id ?? null)}
                                options={githubIntegrations.map((i) => ({
                                    value: i.id,
                                    label: i.display_name || `GitHub #${i.id}`,
                                    icon: <IconGithub />,
                                }))}
                                placeholder="Select a GitHub integration"
                                fullWidth
                            />
                        </LemonField.Pure>

                        {integrationId && (
                            <LemonField.Pure label="Repository">
                                <GitHubRepositoryPicker
                                    integrationId={integrationId}
                                    value={repoName}
                                    onChange={setRepoName}
                                />
                            </LemonField.Pure>
                        )}

                        <LemonField.Pure label="Project name" info="Shown in the UI; can be edited later.">
                            <LemonInput value={name} onChange={setName} placeholder="my-site" />
                        </LemonField.Pure>

                        <LemonField.Pure
                            label="Slug"
                            info="Used for the deployment subdomain. Only letters, numbers, underscores and hyphens."
                        >
                            <LemonInput value={slug} onChange={setSlug} placeholder="my-site" />
                        </LemonField.Pure>

                        {error && <LemonBanner type="error">{error}</LemonBanner>}
                    </>
                )}
            </div>
        </LemonModal>
    )
}
