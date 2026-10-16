import type { IntegrationType } from '~/types'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

export type GitHubConnectStatus = 'loading' | 'error' | 'connected' | 'link-existing' | 'install'

export function githubConnectStatus(
    integrations: IntegrationType[] | null,
    availableInstallations: GitHubAvailableInstallationApi[] | null,
    discoveryFailed: boolean,
    integrationsFailed: boolean
): GitHubConnectStatus {
    if (integrations === null) {
        return integrationsFailed ? 'error' : 'loading'
    }
    // An installation removed or suspended on GitHub can't be used, so it needs a fresh connect.
    if (
        integrations.some(
            (integration) => integration.kind === 'github' && integration.installation_status !== 'unavailable'
        )
    ) {
        return 'connected'
    }
    // Offering a fresh install before discovery answers would send an org that already has the
    // GitHub App through GitHub's configure page instead of linking the existing installation.
    if (availableInstallations === null && !discoveryFailed) {
        return 'loading'
    }
    return availableInstallations && availableInstallations.length > 0 ? 'link-existing' : 'install'
}
