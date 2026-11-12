import { actionsIdTokenSource } from '../actions-id-token'
import type { WorkloadProvider } from '../registry'

const NAME = 'GitHub Actions'

export const GITHUB_ACTIONS: WorkloadProvider = {
    key: 'github_actions',
    name: NAME,
    detect: (env) => env.GITHUB_ACTIONS === 'true',
    ...actionsIdTokenSource(NAME),
    configPath: '.github/workflows',
    nameFromRemote: (remote) =>
        remote.match(
            /^(?:[a-z+]+:\/\/(?:[^@/]*@)?github\.com(?::\d+)?\/|(?:[^@:/]+@)?github\.com:)([\w.-]+\/[\w.-]+?)(?:\.git)?\/?$/i
        )?.[1],
}
