export interface ModelRow {
    model: string
    cost: {
        prompt_token: number
        completion_token: number
        cache_read_token?: number
        cache_write_token?: number
    }
}
