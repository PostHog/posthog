import { LLMGeneration, LLMTrace } from '~/queries/schema'

export function formatLLMUsage(trace: LLMTrace | LLMGeneration): string | null {
    if (typeof trace.inputTokens === 'number') {
        return `${trace.inputTokens} → ${trace.outputTokens || 0} (∑ ${trace.inputTokens + (trace.outputTokens || 0)})`
    }

    return null
}

export function formatLLMLatency(latency: number): string {
    return `${Math.round(latency * 100) / 100}s`
}

const numberFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
})

export function formatLLMCost(cost: number): string {
    return numberFormatter.format(cost)
}
