/**
 * Model resolution + provider registration for the runner.
 *
 * The agent loop (see `loop/driver.ts`) streams through pi-ai's `streamSimple`
 * directly, so there's no client wrapper here anymore — just the helpers that
 * turn a `spec.model` string into a pi-ai `Model` and the one-time provider
 * registration `streamSimple` needs.
 */

import { getModel, KnownProvider, Model, registerBuiltInApiProviders } from '@earendil-works/pi-ai'

// pi-ai ships built-in providers (Anthropic, OpenAI, Google, Mistral, Bedrock,
// …) but only activates them when a caller opts in. Without this, `streamSimple`
// raises "No API provider registered for api: <id>" and the turn fails with a
// stream-level error. One module-level call is enough — it's idempotent. The
// faux test path registers its own provider on top via `registerFauxProvider()`
// (see services/agent-tests/src/harness/faux.ts).
registerBuiltInApiProviders()

/**
 * Resolve a `spec.model` string to a pi-ai `Model`. Format:
 *   "<provider>/<model-id>"           — built-in pi-ai providers
 *   "faux/<model-id>"                 — scripted faux model (tests register first)
 *
 * For custom endpoints (ai-gateway, Ollama, etc.) callers build the Model
 * directly via `posthogAiGatewayModel()` and pass it in.
 */
export function resolveModel(specModel: string): Model<string> {
    const slash = specModel.indexOf('/')
    if (slash === -1) {
        throw new Error(`spec.model must be "<provider>/<model-id>" (got ${JSON.stringify(specModel)})`)
    }
    const provider = specModel.slice(0, slash)
    const modelId = specModel.slice(slash + 1)
    const model = getModel(provider as KnownProvider, modelId as never) as Model<string> | undefined
    if (!model) {
        // pi-ai returns undefined for an unknown (provider, model id) pair. Without
        // this guard the undefined `Model` flows into runSession and crashes
        // `errorContext()` on `deps.model.id` only at the *first error path* —
        // which silently fails every session and surfaces as
        // `Cannot read properties of undefined (reading 'id')` in the logs.
        throw new Error(
            `unknown_model_id: spec.model="${specModel}" — pi-ai has no model "${modelId}" registered ` +
                `for provider "${provider}". Check the pi-ai models registry or upgrade @earendil-works/pi-ai.`
        )
    }
    return model
}

/** Cache of resolved Models keyed by spec.model string. */
const MODEL_CACHE = new Map<string, Model<string>>()

export function resolveModelCached(specModel: string): Model<string> {
    let m = MODEL_CACHE.get(specModel)
    if (!m) {
        m = resolveModel(specModel)
        MODEL_CACHE.set(specModel, m)
    }
    return m
}

/** Clear the resolver cache. Tests call this when re-registering faux models. */
export function clearModelCache(): void {
    MODEL_CACHE.clear()
}
