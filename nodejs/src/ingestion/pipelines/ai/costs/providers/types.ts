export interface ModelCost {
    prompt_token: number
    completion_token: number
    cache_read_token?: number
    cache_write_token?: number
    cache_write_1h_token?: number
    request?: number
    web_search?: number
    image?: number
    image_output?: number
    audio?: number
    audio_output?: number
    input_audio_cache?: number
    internal_reasoning?: number
    /** Rate tiers that replace the rates above once a prompt gets long enough. */
    context_tiers?: ContextLengthTier[]
}

/**
 * What a model charges once a request's prompt passes `min_input_tokens`.
 *
 * A vendor usually moves only some of its rates at the threshold, so every rate
 * is optional: the ones listed here replace the model's base rates, and the ones
 * left out keep them. The threshold is exclusive, matching how vendors publish
 * it ("above 200K tokens").
 */
export type ContextLengthTier = {
    min_input_tokens: number
} & Partial<Omit<ModelCost, 'context_tiers'>>

/** Every `ModelCost` field that carries one rate. `context_tiers` holds a list
 * of rate sets instead, so a per-rate loop has to leave it out. */
export type ModelCostRateField = Exclude<keyof ModelCost, 'context_tiers'>

export type ModelCostByProvider = {
    default: ModelCost
} & Record<string, ModelCost | undefined>

export interface ModelCostRow {
    model: string
    cost: ModelCostByProvider
}

export interface ResolvedModelCost {
    model: string
    provider: string
    cost: ModelCost
}
