import { fetchActionsIdToken } from '../actions-id-token'
import type { WorkloadProvider } from '../registry'

const NAME = 'GitHub Actions'

export const GITHUB_ACTIONS: WorkloadProvider = {
    key: 'github_actions',
    name: NAME,
    issuer: 'https://token.actions.githubusercontent.com',
    docsUrl: 'https://posthog.com/docs/api/workload-identity/github-actions',
    detect: (env) => env.GITHUB_ACTIONS === 'true',
    fetchToken: (runtime, audience) => fetchActionsIdToken(runtime, audience, NAME),
    missingTokenHint:
        'Add `permissions: id-token: write` to the job, so GitHub Actions issues it an OIDC token. Run `hog ci setup` on your machine for the full snippet.',
    configPaths: ['.github/workflows'],
    nameFromRemote: (remote) =>
        remote.match(
            /^(?:[a-z+]+:\/\/(?:[^@/]*@)?github\.com(?::\d+)?\/|(?:[^@:/]+@)?github\.com:)([\w.-]+\/[\w.-]+?)(?:\.git)?\/?$/i
        )?.[1],
}
