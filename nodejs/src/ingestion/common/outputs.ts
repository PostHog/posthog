export const EVENTS_OUTPUT = 'events' as const
export type EventOutput = typeof EVENTS_OUTPUT

export const INGESTION_WARNINGS_OUTPUT = 'ingestion_warnings' as const
export type IngestionWarningsOutput = typeof INGESTION_WARNINGS_OUTPUT

export const DLQ_OUTPUT = 'dlq' as const
export type DlqOutput = typeof DLQ_OUTPUT

export const OVERFLOW_OUTPUT = 'overflow' as const
export type OverflowOutput = typeof OVERFLOW_OUTPUT

export const GROUPS_OUTPUT = 'groups' as const
export type GroupsOutput = typeof GROUPS_OUTPUT
