// TypeScript types for precalculated person property events

export type PreCalculatedPersonProperty = {
    person_id: string // UUID
    team_id: number
    evaluation_timestamp: string // ClickHouse DateTime64(6) format
    condition: string // 16-char conditionHash
    matches: number // 0 = doesn't match, 1 = matches
    source: string // e.g., "cohort_filter_{conditionHash}"
}

export type ProducedPersonPropertyEvent = {
    key: string // person_id
    payload: PreCalculatedPersonProperty
}
