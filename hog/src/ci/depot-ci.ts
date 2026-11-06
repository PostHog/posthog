import { fetchActionsIdToken } from './actions-id-token'
import type { WorkloadProvider } from './providers'

const NAME = 'Depot CI'

export const DEPOT_CI: WorkloadProvider = {
    key: 'depot_ci',
    name: NAME,
    issuer: 'https://identity.depot.dev',
    docsUrl: 'https://posthog.com/docs/api/workload-identity/depot',
    // Only Depot CI sets DEPOT_JOB_URL. Depot runners for GitHub Actions set other DEPOT_ variables,
    // and their jobs get GitHub's tokens.
    detect: (env) => !!env.DEPOT_JOB_URL,
    fetchToken: (runtime, audience) => fetchActionsIdToken(runtime, audience, NAME),
    missingTokenHint:
        'Add `permissions: id-token: write` to the job, so Depot CI issues it an OIDC token. Run `hog ci setup` on your machine for the full snippet.',
    configPaths: ['.depot/workflows'],
    nameFromRemote: (remote) => remote.match(/github\.com[:/]([^/\s]+\/[^/\s]+?)(?:\.git)?\/?$/)?.[1],
    branchConditions: (branch) => ({ event_name: 'push', ref: `refs/heads/${branch}` }),
    requiredConditions: [
        { claim: 'org_id', label: 'Depot organization ID' },
        { claim: 'forge', label: 'forge', defaultValue: 'github' },
    ],
    // PostHog looks the repository up on GitHub, which knows nothing about another forge's IDs.
    canLookUpSubject: (conditions) => conditions.forge === 'github',
    snippet: ({ host, projectId }) =>
        [
            'permissions:',
            '  id-token: write # lets hog get an OIDC token for PostHog',
            '  contents: read',
            'env:',
            `  HOG_HOST: ${host}`,
            `  HOG_PROJECT_ID: "${projectId}"`,
        ].join('\n'),
}
