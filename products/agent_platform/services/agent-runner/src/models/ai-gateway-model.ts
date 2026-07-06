/**
 * Build a pi-ai `Model` that routes through PostHog's ai-gateway (the
 * external Go service that fronts every provider and owns usage / billing —
 * see github.com/PostHog/ai-gateway).
 *
 * The gateway is designed as a drop-in proxy: a customer points an existing
 * OpenAI / Anthropic SDK at `<gateway>/v1` instead of the provider's URL and
 * sends the provider-native SKU as `model`. We mirror that here — resolve
 * the spec.model via pi-ai (which picks the correct api shape per provider),
 * then override only `baseUrl` (to the right gateway endpoint for that shape)
 * and `provider` (so logs / analytics attribute traffic to the gateway).
 *
 * Routing notes:
 *   - openai-completions / openai-responses → SDK appends `/chat/completions`
 *     or `/responses` to baseUrl, so we keep the `/v1` suffix on baseUrl.
 *   - anthropic-messages → Anthropic SDK appends `/v1/messages` itself, so
 *     we strip the trailing `/v1` from baseUrl.
 *
 * Auth: the gateway authenticates the customer with `Authorization: Bearer
 * <phs_…>` (it reads only that header). pi-ai's openai shapes already send the
 * apiKey as `Authorization: Bearer`, but its anthropic-messages shape sends it
 * as `x-api-key` with no `Authorization` — so a Claude model would 401 at the
 * gateway's auth tier. We pin `Authorization: Bearer <key>` on the model so
 * every shape authenticates the way the gateway expects. pi-ai still sends the
 * key as the provider credential too (x-api-key for Anthropic), which the
 * gateway overrides when it forwards to the upstream provider.
 */

import type { Model } from '@earendil-works/pi-ai'

import { resolveModel } from './pi-client'

export interface AiGatewayModelOpts {
    /** Spec.model in canonical form, e.g. `openai/gpt-4o`. */
    specModel: string
    /** Gateway root with `/v1` suffix, e.g. `http://localhost:8080/v1`. */
    baseUrl: string
    /**
     * The gateway bearer — a `phs_` project secret key with `llm_gateway:read`.
     * Pinned as `Authorization: Bearer <key>` on the model so the
     * anthropic-messages shape (which otherwise sends only `x-api-key`)
     * authenticates against the gateway. See the auth note above.
     */
    apiKey: string
}

/**
 * Map a spec.model string (e.g. `openai/gpt-4o`) to the provider-native SKU
 * the ai-gateway's admission layer accepts. The gateway's `CanonicalForSKU`
 * lookup is keyed on bare ids (`gpt-4o`, `claude-sonnet-4-5`), not on the
 * canonical `<provider>/<model>` form.
 */
export function aiGatewaySkuFor(specModel: string): string {
    const slash = specModel.indexOf('/')
    return slash === -1 ? specModel : specModel.slice(slash + 1)
}

export function posthogAiGatewayModel(opts: AiGatewayModelOpts): Model<string> {
    const native = resolveModel(opts.specModel)
    return {
        ...native,
        id: aiGatewaySkuFor(opts.specModel),
        provider: 'posthog-ai-gateway',
        baseUrl: gatewayBaseUrlForApi(native.api, opts.baseUrl),
        headers: {
            ...native.headers,
            Authorization: `Bearer ${opts.apiKey}`,
        },
    }
}

function gatewayBaseUrlForApi(api: string, root: string): string {
    if (api === 'anthropic-messages') {
        return root.replace(/\/v1\/?$/, '')
    }
    return root.endsWith('/v1') || root.endsWith('/v1/') ? root : `${root}/v1`
}
