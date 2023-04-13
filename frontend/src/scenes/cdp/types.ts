export type ConnectionChoiceType = {
    id: string
    name: string
    image_url: string
    type: 'Event streaming' | 'Batch export'
}

export type ConnectionType = {
    id: string
    name: string
    status: string
    type: 'Event streaming' | 'Batch export'
    successRate: string
    image_url: string
}
