// Chunk-id-only injection. `e._posthogChunkIds[stack] = chunkId` on the global.
pub const CODE_SNIPPET_TEMPLATE: &str = r#"!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{},n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();"#;

// Chunk-id + release injection. Sets `e._posthogRelease` (first-wins, so the first
// loaded chunk pins the release) alongside the chunk-id map. The SDK reads the object
// off the global and rides it onto every event. Release name/version placeholders are
// filled with JSON-encoded string literals, so they carry their own quotes.
pub const CODE_SNIPPET_WITH_RELEASE_TEMPLATE: &str = r#"!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{};e._posthogRelease=e._posthogRelease||{name:__POSTHOG_RELEASE_NAME__,version:__POSTHOG_RELEASE_VERSION__};var n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();"#;

pub const CHUNKID_COMMENT_PREFIX: &str = "\n//# chunkId=__POSTHOG_CHUNK_ID__";
pub const CHUNKID_PLACEHOLDER: &str = "__POSTHOG_CHUNK_ID__";
pub const RELEASE_NAME_PLACEHOLDER: &str = "__POSTHOG_RELEASE_NAME__";
pub const RELEASE_VERSION_PLACEHOLDER: &str = "__POSTHOG_RELEASE_VERSION__";

// Fixed namespace for deriving deterministic (content-addressed) chunk ids via UUIDv5.
// Same minified bytes in, same chunk id out — across machines and rebuilds — so re-uploads
// dedupe and symbol sets stay stable without a per-build random id.
pub const CHUNK_ID_NAMESPACE: uuid::Uuid =
    uuid::Uuid::from_u128(0x0e9b3c7a5d1f42a8b6c4e2d0f8a17593);
