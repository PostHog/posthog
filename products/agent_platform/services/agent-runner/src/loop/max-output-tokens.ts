// Resolves the per-turn max_tokens we send to the provider.
// Stack: spec.limits.max_output_tokens (or reasoning-aware default) →
// clamped to min(model.maxTokens, config override).
import type { ReasoningEffort } from '@posthog/agent-shared'

export interface ResolveMaxOutputTokensInput {
    modelMaxTokens: number
    configOverride: number | undefined
    specRequested: number | undefined
    reasoning: ReasoningEffort | undefined
}

export interface ResolvedMaxOutputTokens {
    value: number
    clamped: { requested: number; ceiling: number; source: 'config' | 'model' } | null
}

export function defaultMaxOutputTokensForReasoning(reasoning: ReasoningEffort | undefined): number {
    switch (reasoning) {
        case 'low':
            return 8192
        case 'medium':
            return 16384
        case 'high':
        case 'xhigh':
            return 24576
        case 'minimal':
        case undefined:
        default:
            return 4096
    }
}

export function resolveMaxOutputTokens(input: ResolveMaxOutputTokensInput): ResolvedMaxOutputTokens {
    const requested = input.specRequested ?? defaultMaxOutputTokensForReasoning(input.reasoning)
    const ceiling = Math.min(input.modelMaxTokens, input.configOverride ?? Infinity)
    if (requested <= ceiling) {
        return { value: requested, clamped: null }
    }
    const source: 'config' | 'model' =
        input.configOverride !== undefined && input.configOverride < input.modelMaxTokens ? 'config' : 'model'
    return { value: ceiling, clamped: { requested, ceiling, source } }
}
