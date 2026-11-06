import type { Env, Runtime } from '@/core/runtime'
import type { Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import type { ProviderIdToken } from '@/posthog/tokens'

import { GITHUB_ACTIONS } from './github-actions'
import { GITLAB } from './gitlab'

export type WorkloadConditions = Record<string, string>

// A CI provider whose OIDC token PostHog exchanges for a workload token. The backend keeps the
// matching entry in posthog/workload_identity/providers.py, under the same key and issuer.
export interface WorkloadProvider {
    readonly key: string
    readonly name: string
    readonly issuer: string
    readonly docsUrl: string
    detect(env: Env): boolean
    // Resolves to undefined when the job isn't set up to get a token, so other credentials can apply.
    // Throws when the provider refuses a token the job asked for.
    fetchToken(runtime: Runtime, audience: Host): Promise<ProviderIdToken | undefined>
    missingTokenHint: string

    // The rest is for `hog ci setup`, which runs in the repository on a person's machine.
    // Paths, relative to the repository root, that only a repository using this provider's CI has.
    readonly configPaths: readonly string[]
    nameFromRemote(remote: string): string | undefined
    branchConditions(branch: string): WorkloadConditions
    // Undefined for a provider whose token names no environment.
    environmentConditions?(environment: string): WorkloadConditions
    snippet(target: { host: Host; projectId: ProjectId }): string
}

export const WORKLOAD_PROVIDERS: readonly WorkloadProvider[] = [GITHUB_ACTIONS, GITLAB]

export function detectWorkloadProvider(
    env: Env,
    providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS
): WorkloadProvider | undefined {
    return providers.find((provider) => provider.detect(env))
}
