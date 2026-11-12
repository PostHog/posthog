import { z } from 'zod'

import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'
import { sendRequest } from '@/posthog/api'
import type { Host } from '@/posthog/host'
import { ProviderIdTokenSchema, type ProviderIdToken } from '@/posthog/tokens'

import type { WorkloadProvider } from './registry'

// The OIDC token request GitHub Actions defines. CI services that run Actions workflows reuse it, so
// their providers share this module.

const REQUEST_TIMEOUT_MS = 30_000

// GitHub Actions and Depot CI set both only for a job with `permissions: id-token: write`.
const IdTokenResponse = z.object({ value: ProviderIdTokenSchema })

export async function fetchActionsIdToken(
    runtime: Runtime,
    audience: Host,
    providerName: string
): Promise<ProviderIdToken | undefined> {
    const requestUrl = runtime.env.ACTIONS_ID_TOKEN_REQUEST_URL
    const requestToken = runtime.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN
    if (!requestUrl || !requestToken) {
        return undefined
    }
    const url = URL.parse(requestUrl)
    if (url === null) {
        throw new HogError(
            'oidc_token_unavailable',
            `${providerName} set ACTIONS_ID_TOKEN_REQUEST_URL to something that isn't a URL.`
        )
    }
    url.searchParams.set('audience', audience)
    const response = await sendRequest(runtime.fetch, url, {
        method: 'GET',
        token: requestToken,
        timeoutMs: REQUEST_TIMEOUT_MS,
    })
    if (!response.ok) {
        throw new HogError(
            'oidc_token_unavailable',
            `${providerName} didn't issue an OIDC token: it answered with HTTP ${response.status}.`,
            'Run the job again. If it keeps failing, check the provider status page.'
        )
    }
    return parseOrThrow(IdTokenResponse, response.json, {
        code: 'oidc_token_unavailable',
        context: `${providerName}'s OIDC token answer isn't what hog expects.`,
    }).value
}

export function actionsIdTokenSource(providerName: string): Pick<WorkloadProvider, 'fetchToken' | 'missingTokenHint'> {
    return {
        fetchToken: (runtime, audience) => fetchActionsIdToken(runtime, audience, providerName),
        missingTokenHint: `Add \`permissions: id-token: write\` to the job, so ${providerName} issues it an OIDC token. Run \`hog ci setup\` on your machine for the full snippet.`,
    }
}
