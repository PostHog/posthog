import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'

export function GitHubPublicRepositoryWarning({
    integrationId,
    repository,
}: {
    integrationId: number
    repository: string
}): JSX.Element | null {
    const { repositories } = useValues(githubIntegrationLogic({ id: integrationId }))
    // Repositories cached before GitHub reported visibility have no `private` field, so only a
    // confirmed public repository gets the warning.
    const isPublic = repositories.find((repo) => repo.name === repository)?.private === false

    if (!isPublic) {
        return null
    }
    return (
        <LemonBanner type="warning">
            This repository is public, so anyone can read the issues this creates and the event details in them.
        </LemonBanner>
    )
}
