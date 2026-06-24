import { defineNativeTool, Type } from '@posthog/agent-shared'

/**
 * `@posthog/agent-applications-models` — served models + pricing, so the Agent
 * Builder picks a `model_policy` model against what will actually run instead of
 * guessing a string that 400s. Reference models by canonical id. Reads through
 * `ctx.gatewayCatalog`; returns [] when the gateway is unreachable.
 */

/** Per-token USD → per-Mtok, rounded so the model sees `3` not `0.0000030004`. */
function perMTok(perToken: number | undefined): number | undefined {
    if (perToken === undefined) {
        return undefined
    }
    return Math.round(perToken * 1e6 * 1000) / 1000
}

export const posthogListModelsV1 = defineNativeTool({
    id: '@posthog/agent-applications-models',
    description:
        'List the AI models the gateway serves — canonical id, provider, context window, and pricing (USD per million tokens). Use to choose a `spec.model_policy` model or quote cost. Reference a model by its canonical id (e.g. "anthropic/claude-haiku-4.5"); that is the form `model_policy` validates against.',
    args: Type.Object({}),
    returns: Type.Object({
        models: Type.Array(
            Type.Object({
                model: Type.String(),
                provider: Type.String(),
                context_window: Type.Number(),
                pricing_usd_per_mtok: Type.Object({
                    input: Type.Number(),
                    output: Type.Number(),
                    cache_read: Type.Optional(Type.Number()),
                    cache_write: Type.Optional(Type.Number()),
                }),
            })
        ),
    }),
    cost_hint: 'cheap',
    async run(_args, ctx) {
        if (!ctx.gatewayCatalog) {
            ctx.log('warn', 'models.catalog_unavailable', {})
            return { models: [] }
        }
        const catalog = await ctx.gatewayCatalog.list()
        const models = catalog
            .map((m) => ({
                model: m.canonical,
                provider: m.owned_by,
                context_window: m.context_window,
                pricing_usd_per_mtok: {
                    input: perMTok(m.pricing.prompt) ?? 0,
                    output: perMTok(m.pricing.completion) ?? 0,
                    cache_read: perMTok(m.pricing.cache_read),
                    cache_write: perMTok(m.pricing.cache_write),
                },
            }))
            .sort((a, b) => a.model.localeCompare(b.model))
        ctx.log('info', 'models.listed', { count: models.length })
        return { models }
    },
})
