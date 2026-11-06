import type { Env, Runtime } from '@/core/runtime'
import type { Host } from '@/posthog/host'
import type { ProviderIdToken } from '@/posthog/tokens'

// A CI provider whose OIDC token PostHog exchanges for a workload token. The backend keeps the
// matching entry in posthog/workload_identity/providers.py, under the same key.
export interface WorkloadProvider {
    readonly key: string
    readonly name: string
    detect(env: Env): boolean
    // Resolves to undefined when the job isn't set up to get a token, so other credentials can apply.
    // Throws when the provider refuses a token the job asked for.
    fetchToken(runtime: Runtime, audience: Host): Promise<ProviderIdToken | undefined>
    missingTokenHint: string
}

export const WORKLOAD_PROVIDERS: readonly WorkloadProvider[] = []

export function detectWorkloadProvider(
    env: Env,
    providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS
): WorkloadProvider | undefined {
    return providers.find((provider) => provider.detect(env))
}
