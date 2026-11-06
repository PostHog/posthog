import { fetchActionsIdToken } from './actions-id-token'
import type { WorkloadProvider } from './providers'

const NAME = 'GitHub Actions'

export const GITHUB_ACTIONS: WorkloadProvider = {
    key: 'github_actions',
    name: NAME,
    issuer: 'https://token.actions.githubusercontent.com',
    docsUrl: 'https://posthog.com/docs/api/workload-identity/github-actions',
    detect: (env) => env.GITHUB_ACTIONS === 'true' && !env.DEPOT_JOB_URL,
    fetchToken: (runtime, audience) => fetchActionsIdToken(runtime, audience, NAME),
    missingTokenHint:
        'Add `permissions: id-token: write` to the job, so GitHub Actions issues it an OIDC token. Run `hog ci setup` on your machine for the full snippet.',
    configPaths: ['.github/workflows'],
    nameFromRemote: (remote) => remote.match(/github\.com[:/]([^/\s]+\/[^/\s]+?)(?:\.git)?\/?$/)?.[1],
    // A `pull_request_target` run from a fork carries the base branch as its ref, so a branch alone would
    // trust code from the fork. Only pushes run code that is on the branch.
    branchConditions: (branch) => ({ event_name: 'push', ref: `refs/heads/${branch}` }),
    environmentConditions: (environment) => ({ environment }),
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
