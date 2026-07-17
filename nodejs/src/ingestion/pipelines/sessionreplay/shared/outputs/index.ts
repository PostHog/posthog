// Output names shared between the session-recording consumer and the
// session-replay recording-api. Generic outputs (DLQ, ingestion warnings,
// overflow, etc.) live in `common/outputs`.

export const REPLAY_EVENTS_OUTPUT = 'replay_events' as const
export type ReplayEventsOutput = typeof REPLAY_EVENTS_OUTPUT

export const SESSION_FEATURES_OUTPUT = 'session_features' as const
export type SessionFeaturesOutput = typeof SESSION_FEATURES_OUTPUT

// Anonymized block metadata for the ML mirror; only the mirror deployment produces to it.
export const ML_BLOCK_METADATA_OUTPUT = 'ml_block_metadata' as const
export type MlBlockMetadataOutput = typeof ML_BLOCK_METADATA_OUTPUT
