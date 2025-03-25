export interface ModelRow {
    model: string
    cost: {
        prompt_token: number
        completion_token: number
    }
}
