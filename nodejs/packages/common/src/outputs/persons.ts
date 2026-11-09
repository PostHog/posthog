// Person-data output names, shared by the common persons data layer and the analytics lane.
export const PERSONS_OUTPUT = 'persons' as const
export type PersonsOutput = typeof PERSONS_OUTPUT

export const PERSON_DISTINCT_IDS_OUTPUT = 'person_distinct_ids' as const
export type PersonDistinctIdsOutput = typeof PERSON_DISTINCT_IDS_OUTPUT

export const PERSON_MERGE_EVENTS_OUTPUT = 'person_merge_events' as const
export type PersonMergeEventsOutput = typeof PERSON_MERGE_EVENTS_OUTPUT
