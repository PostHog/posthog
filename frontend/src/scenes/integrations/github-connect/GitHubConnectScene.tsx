import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { GitHubInstallationLink } from 'scenes/integrations/components/GithubIntegration'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { githubConnectSceneLogic } from './githubConnectSceneLogic'

export const scene: SceneExport = {
    component: GitHubConnectScene,
    logic: githubConnectSceneLogic,
}

export function GitHubConnectScene(): JSX.Element {
    const {
        status,
        redirectingToGithub,
        githubIntegrations,
        githubAvailableInstallations,
        githubAvailableInstallationsResponse,
        linkedGithubInstallationLoading,
        integrationsLoading,
    } = useValues(githubConnectSceneLogic)
    const { continueToGithub, linkInstallation, loadIntegrations } = useActions(githubConnectSceneLogic)
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentProject } = useValues(projectLogic)

    const installations = githubAvailableInstallations ?? []
    const connectedAccount = githubIntegrations.find(
        (integration) => integration.installation_status !== 'unavailable'
    )?.display_name

    return (
        <BridgePage view="github-connect">
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2 text-center">
                    <h2 className="text-xl font-semibold m-0">Connect GitHub to PostHog</h2>
                    <p className="text-secondary m-0">
                        Your AI assistant needs access to GitHub to set up PostHog in your repository.
                    </p>
                </div>
                <LemonCard hoverEffect={false} className="p-4">
                    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 m-0 text-sm">
                        <dt className="text-secondary">PostHog account</dt>
                        <dd className="m-0 font-semibold truncate" title={user?.email}>
                            {user?.email}
                        </dd>
                        <dt className="text-secondary">Organization</dt>
                        <dd className="m-0 font-semibold truncate" title={currentOrganization?.name}>
                            {currentOrganization?.name}
                        </dd>
                        <dt className="text-secondary">Project</dt>
                        <dd className="m-0 font-semibold truncate" title={currentProject?.name}>
                            {currentProject?.name}
                        </dd>
                    </dl>
                </LemonCard>
                {status === 'loading' ? (
                    <div className="flex items-center justify-center gap-2 text-secondary">
                        <Spinner />
                        <span>Checking your GitHub connection…</span>
                    </div>
                ) : status === 'error' ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () => loadIntegrations(),
                            loading: integrationsLoading,
                            'data-attr': 'github-connect-retry',
                        }}
                    >
                        Couldn't check this project's GitHub connection. Retry, and if it keeps failing, reload the
                        page.
                    </LemonBanner>
                ) : status === 'connected' ? (
                    <LemonBanner type="success">
                        {connectedAccount ? (
                            <>
                                This project is connected to GitHub through <strong>{connectedAccount}</strong>.
                            </>
                        ) : (
                            <>This project is connected to GitHub.</>
                        )}{' '}
                        Go back to your chat and tell the assistant to continue.
                    </LemonBanner>
                ) : status === 'link-existing' ? (
                    <>
                        <LemonBanner type="info" hideIcon>
                            <div className="flex flex-col gap-3">
                                <span className="font-normal">
                                    {installations.length > 1 ? (
                                        <>PostHog is already installed on more than one GitHub account.</>
                                    ) : (
                                        <>
                                            PostHog is already installed on the GitHub account{' '}
                                            <strong>
                                                {installations[0].account_name ?? installations[0].installation_id}
                                            </strong>
                                            .
                                        </>
                                    )}{' '}
                                    Connect it to this project, so you don't need to install it again.
                                </span>
                                <div className="flex flex-wrap gap-2">
                                    <GitHubInstallationLink
                                        installations={installations}
                                        personalGithubLogin={
                                            githubAvailableInstallationsResponse?.personal_github_login
                                        }
                                        loading={linkedGithubInstallationLoading}
                                        onLink={linkInstallation}
                                        emphasizeInstallation
                                    />
                                </div>
                            </div>
                        </LemonBanner>
                        <LemonButton
                            type="secondary"
                            center
                            fullWidth
                            icon={<IconGithub />}
                            loading={redirectingToGithub}
                            disabledReason={linkedGithubInstallationLoading ? 'Connecting the installation' : undefined}
                            onClick={continueToGithub}
                            data-attr="github-connect-different-account"
                        >
                            Connect a different GitHub account
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton
                        type="primary"
                        center
                        fullWidth
                        icon={<IconGithub />}
                        loading={redirectingToGithub}
                        onClick={continueToGithub}
                        data-attr="github-connect-continue"
                    >
                        Continue to GitHub
                    </LemonButton>
                )}
            </div>
        </BridgePage>
    )
}
