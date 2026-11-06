import type { Env, Runtime } from '@/core/runtime'
import type { Host } from '@/posthog/host'
import type { ProjectId } from '@/posthog/ids'
import type { ProviderIdToken } from '@/posthog/tokens'

import { DEPOT_CI } from './depot-ci'
import { GITHUB_ACTIONS } from './github-actions'
import { GITLAB } from './gitlab'

export type WorkloadConditions = Record<string, string>

// The backend keeps the matching entry in posthog/workload_identity/providers.py, under the same key and issuer.
export interface WorkloadProvider {
    readonly key: string
    readonly name: string
    readonly issuer: string
    readonly docsUrl: string
    detect(env: Env): boolean
    // Resolves to undefined when the job isn't set up to get a token, so other credentials can apply.
    fetchToken(runtime: Runtime, audience: Host): Promise<ProviderIdToken | undefined>
    missingTokenHint: string

    // The rest is for `hog ci setup`. Config paths are relative to the repository root.
    readonly configPaths: readonly string[]
    nameFromRemote(remote: string): string | undefined
    branchConditions(branch: string): WorkloadConditions
    // Undefined for a provider whose token names no environment.
    environmentConditions?(environment: string): WorkloadConditions
    readonly requiredConditions?: readonly { claim: string; label: string; defaultValue?: string }[]
    // False when PostHog's subject lookup can't serve these conditions, so the person passes --subject-id.
    canLookUpSubject?(conditions: WorkloadConditions): boolean
    snippet(target: { host: Host; projectId: ProjectId }): string
}

export const WORKLOAD_PROVIDERS: readonly WorkloadProvider[] = [GITHUB_ACTIONS, GITLAB, DEPOT_CI]

export function detectWorkloadProvider(
    env: Env,
    providers: readonly WorkloadProvider[] = WORKLOAD_PROVIDERS
): WorkloadProvider | undefined {
    return providers.find((provider) => provider.detect(env))
}
