import { fetchActionsIdToken } from '../actions-id-token'
import { GITHUB_ACTIONS } from '../github-actions/github-actions'
import type { WorkloadProvider } from '../registry'

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
    nameFromRemote: GITHUB_ACTIONS.nameFromRemote,
}
