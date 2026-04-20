export interface ModelCost {
    prompt_token: number
    completion_token: number
    cache_read_token?: number
    cache_write_token?: number
    request?: number
    web_search?: number
    image?: number
    image_output?: number
    audio?: number
    input_audio_cache?: number
    internal_reasoning?: number
}

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
