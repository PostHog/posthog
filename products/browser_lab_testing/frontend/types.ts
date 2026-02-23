export interface BrowserLabTestType {
    id: string
    name: string
    url: string
    steps: Record<string, unknown>[]
    secrets: Record<string, string | { secret: true }>
    created_by: number | null
    created_at: string
    updated_at: string
}
