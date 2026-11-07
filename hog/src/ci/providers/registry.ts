import type { Env, Runtime } from '@/core/runtime'
import type { Host } from '@/posthog/host'
import type { ProviderIdToken } from '@/posthog/tokens'

import { GITHUB_ACTIONS } from './github-actions/github-actions'

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

export const WORKLOAD_PROVIDERS: readonly WorkloadProvider[] = [GITHUB_ACTIONS]

export function detectWorkloadProvider(
    env: Env,
    providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS
): WorkloadProvider | undefined {
    return providers.find((provider) => provider.detect(env))
}
