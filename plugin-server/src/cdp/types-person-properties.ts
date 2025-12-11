// TypeScript types for precalculated person properties events

export type PreCalculatedPersonProperties = {
    person_id: string // UUID
    team_id: number
    condition: string // 16-char conditionHash
    matches: boolean // true = matches, false = doesn't match
    source: string // e.g., "cohort_filter_{conditionHash}"
}

export type ProducedPersonPropertiesEvent = {
    key: string // person_id
    payload: PreCalculatedPersonProperties
}
