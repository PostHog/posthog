pub const CODE_SNIPPET_TEMPLATE: &str = r#"!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{},n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();"#;

// The SDK only reads `_posthogReleaseId` when it is a non-empty string, so the placeholder is
// filled with a JSON-encoded string literal that carries its own quotes.
pub const CODE_SNIPPET_WITH_RELEASE_TEMPLATE: &str = r#"!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{};e._posthogReleaseId=e._posthogReleaseId||__POSTHOG_RELEASE_ID__;var n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();"#;

pub const CHUNKID_COMMENT_PREFIX: &str = "\n//# chunkId=__POSTHOG_CHUNK_ID__";
pub const CHUNKID_PLACEHOLDER: &str = "__POSTHOG_CHUNK_ID__";
/// The placeholder as it appears in the snippet templates: inside a JS string literal. Snippet
/// rendering replaces it quotes-and-all with a JSON-encoded value, so the id can't break out.
pub const QUOTED_CHUNKID_PLACEHOLDER: &str = "\"__POSTHOG_CHUNK_ID__\"";
pub const RELEASE_ID_PLACEHOLDER: &str = "__POSTHOG_RELEASE_ID__";

// UUIDv5 namespace for content-addressed chunk ids: the same minified bytes give the same id
// across machines and rebuilds, so re-uploads dedupe.
pub const CHUNK_ID_NAMESPACE: uuid::Uuid =
    uuid::Uuid::from_u128(0x0e9b3c7a5d1f42a8b6c4e2d0f8a17593);
