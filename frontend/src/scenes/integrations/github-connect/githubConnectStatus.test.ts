import type { IntegrationType } from '~/types'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

import { GitHubConnectStatus, githubConnectStatus } from './githubConnectStatus'

const githubIntegration = { id: 1, kind: 'github' } as IntegrationType
const unavailableGithubIntegration = { id: 3, kind: 'github', installation_status: 'unavailable' } as IntegrationType
const slackIntegration = { id: 2, kind: 'slack' } as IntegrationType
const installation: GitHubAvailableInstallationApi = {
    installation_id: '123',
    account_name: 'example-org',
    account_type: 'Organization',
    source_team_id: 7,
    source_team_name: 'Another project',
}

describe('githubConnectStatus', () => {
    test.each<
        [string, IntegrationType[] | null, GitHubAvailableInstallationApi[] | null, boolean, GitHubConnectStatus]
    >([
        ['integrations not loaded', null, null, false, 'loading'],
        ['project already connected, discovery pending', [githubIntegration], null, false, 'connected'],
        ['discovery pending', [slackIntegration], null, false, 'loading'],
        ['installation removed on GitHub', [unavailableGithubIntegration], [], false, 'install'],
        ['installation in another project', [slackIntegration], [installation], false, 'link-existing'],
        ['no installation anywhere', [], [], false, 'install'],
        ['discovery failed', [], null, true, 'install'],
    ])('%s', (_, integrations, installations, discoveryFailed, expected) => {
        expect(githubConnectStatus(integrations, installations, discoveryFailed)).toEqual(expected)
    })
})
