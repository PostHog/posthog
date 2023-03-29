export type EventType = {
    uuid: string
    distinct_id: string
    team_id: number
    event: string
    timestamp: string
    person_id: string
    properties: Record<string, any>
    person_properties: Record<string, any>
    group_properties: Record<string, any>
}

export type AutomationType = {
    id: number
    config: any
}
