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

// Original image bytes for the out-of-band scrub lane (key = `image:<pseudoTeam>:<hash>`);
// only the mirror deployment produces to it.
export const ML_IMAGE_SCRUB_OUTPUT = 'ml_image_scrub' as const
export type MlImageScrubOutput = typeof ML_IMAGE_SCRUB_OUTPUT

// Original URLs of remote images for the fetch lane (key = host); only the mirror deployment
// produces to it. The key is the host and not the ref, because the fetcher controls its request
// rate for each host, and one pod must own one host to do that without a distributed lock.
export const ML_IMAGE_FETCH_OUTPUT = 'ml_image_fetch' as const
export type MlImageFetchOutput = typeof ML_IMAGE_FETCH_OUTPUT
