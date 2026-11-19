import { actionsIdTokenSource } from '../actions-id-token'
import { GITHUB_ACTIONS } from '../github-actions/github-actions'
import type { WorkloadProvider } from '../registry'

const NAME = 'Depot CI'

export const DEPOT_CI: WorkloadProvider = {
    key: 'depot_ci',
    name: NAME,
    // Only Depot CI sets DEPOT_JOB_URL. Depot runners for GitHub Actions set other DEPOT_ variables,
    // and their jobs get GitHub's tokens.
    detect: (env) => !!env.DEPOT_JOB_URL,
    ...actionsIdTokenSource(NAME),
    configPath: '.depot/workflows',
    nameFromRemote: GITHUB_ACTIONS.nameFromRemote,
}
