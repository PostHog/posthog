import type { Env, Runtime } from '@/core/runtime'
import type { Host } from '@/posthog/host'
import type { ProviderIdToken } from '@/posthog/tokens'

import { DEPOT_CI } from './depot/depot-ci'
import { GITHUB_ACTIONS } from './github-actions/github-actions'
import { GITLAB } from './gitlab/gitlab'

export type WorkloadConditions = Record<string, string>

// The backend keeps the matching entry in posthog/workload_identity/providers.py, under the same key.
export interface WorkloadProvider {
    readonly key: string
    readonly name: string
    detect(env: Env): boolean
    // Resolves to undefined when the job isn't set up to get a token, so other credentials can apply.
    fetchToken(runtime: Runtime, audience: Host): Promise<ProviderIdToken | undefined>
    missingTokenHint: string

    // The rest is for `hog ci setup`. The config path is relative to the repository root.
    readonly configPath: string
    nameFromRemote(remote: string): string | undefined
}

// Detection takes the first match, so a provider that runs other providers' jobs, like Depot CI running
// GitHub Actions workflows, comes before them.
export const WORKLOAD_PROVIDERS: readonly WorkloadProvider[] = [DEPOT_CI, GITHUB_ACTIONS, GITLAB]

export function detectWorkloadProvider(
    env: Env,
    providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS
): WorkloadProvider | undefined {
    return providers.find((provider) => provider.detect(env))
}
