// Person-data output names, shared by the common persons data layer and the analytics lane.
export const PERSONS_OUTPUT = 'persons' as const
export type PersonsOutput = typeof PERSONS_OUTPUT

export const PERSON_DISTINCT_IDS_OUTPUT = 'person_distinct_ids' as const
export type PersonDistinctIdsOutput = typeof PERSON_DISTINCT_IDS_OUTPUT
